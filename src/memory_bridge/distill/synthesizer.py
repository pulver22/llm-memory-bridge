"""Distillation pipeline orchestrating chunking, redaction, and 4-section synthesis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from memory_bridge.distill.extractive import (
    REQUIRED_SECTIONS,
    distill_extractive,
    render_context_document,
)
from memory_bridge.distill.providers import LLMProvider, get_provider
from memory_bridge.utils import redact_secrets, slugify

_SYSTEM_PROMPT = (
    "You are a technical memory distiller for software engineering projects. "
    "Condense verbose conversation transcripts into a high-signal, factual Markdown summary "
    "using ONLY the exact four H2 headings below:\n"
    "## Finalised Decisions & Architecture\n"
    "## Active Work & Current State\n"
    "## Key Facts, Constraints & Parameters\n"
    "## Open Questions & Next Steps\n\n"
    "Rules:\n"
    "- Use concise bullet points (`- `).\n"
    "- Omit greetings, filler, and abandoned ideas unless explicitly marked as rejected.\n"
    "- Never invent facts, paths, versions, or secrets not present in the source.\n"
    "- If a section has nothing to report, output `- None recorded yet.`."
)

_PRIORITY_FILENAMES = ("PROJECT_MEMORY.md", "CODEX_PROJECT_MEMORY.md", "project_prior_context.md")


@dataclass(slots=True)
class DistillResult:
    """Result returned by distill_memory()."""

    output_path: Path | None
    content: str
    provider: str
    model: str | None
    chunks_processed: int
    secrets_redacted: int
    source_files: list[str]


def collect_input_texts(inputs: list[Path]) -> tuple[str, list[str]]:
    """Collect and concatenate text from input files or directories."""
    resolved_files: list[Path] = []
    seen: set[Path] = set()

    for raw_input in inputs:
        path = Path(raw_input).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Distill input path does not exist: {path}")
        if path.is_file():
            if path not in seen:
                seen.add(path)
                resolved_files.append(path)
        elif path.is_dir():
            candidates = sorted(
                p
                for p in path.rglob("*")
                if p.is_file()
                and p.suffix.lower() in {".md", ".txt"}
                and p.name != "INDEX.md"
                and "raw" not in p.parts
            )
            candidates.sort(
                key=lambda p: (
                    0 if p.name in _PRIORITY_FILENAMES else 1,
                    str(p),
                )
            )
            for candidate in candidates:
                if candidate not in seen:
                    seen.add(candidate)
                    resolved_files.append(candidate)

    if not resolved_files:
        raise ValueError("No readable Markdown or text files found in distill inputs.")

    combined_parts: list[str] = []
    source_names: list[str] = []
    for file_path in resolved_files:
        content = file_path.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            continue
        source_names.append(file_path.name)
        combined_parts.append(f"<!-- source: {file_path.name} -->\n\n{content}")

    if not combined_parts:
        raise ValueError("All distill input files are empty.")

    return "\n\n---\n\n".join(combined_parts), source_names


def chunk_text(text: str, chunk_chars: int) -> list[str]:
    """Split text into chunks of at most chunk_chars along paragraph boundaries."""
    if chunk_chars <= 0 or len(text) <= chunk_chars:
        return [text]

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2
        if current and current_len + para_len > chunk_chars:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        if len(para) > chunk_chars:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            for start in range(0, len(para), chunk_chars):
                chunks.append(para[start : start + chunk_chars])
        else:
            current.append(para)
            current_len += para_len

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _strip_outer_fences_and_frontmatter(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5 :].strip()
    return text


def _match_canonical_section(heading_text: str) -> str | None:
    normalized = re.sub(r"[^a-z]+", " ", heading_text.lower()).strip()
    for section in REQUIRED_SECTIONS:
        sec_norm = re.sub(r"[^a-z]+", " ", section.lower()).strip()
        if normalized == sec_norm:
            return section
    if "decision" in normalized or "architecture" in normalized:
        return "Finalised Decisions & Architecture"
    if "active" in normalized or "current state" in normalized:
        return "Active Work & Current State"
    if "fact" in normalized or "constraint" in normalized or "parameter" in normalized:
        return "Key Facts, Constraints & Parameters"
    if "question" in normalized or "next step" in normalized:
        return "Open Questions & Next Steps"
    return None


def normalize_four_sections(
    raw_markdown: str,
    project_name: str,
    project_slug: str,
    source_files: list[str],
    provider: str,
    model: str | None,
) -> str:
    """Normalize LLM output into canonical YAML frontmatter + 4 required sections."""
    cleaned = _strip_outer_fences_and_frontmatter(raw_markdown)
    parsed_sections: dict[str, list[str]] = {sec: [] for sec in REQUIRED_SECTIONS}
    current_section: str | None = None

    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading_match = re.match(r"^#{2,3}\s+(.+)$", line)
        if heading_match:
            matched = _match_canonical_section(heading_match.group(1))
            if matched:
                current_section = matched
                continue
        if current_section is None:
            continue
        if line.startswith("# "):
            continue
        if line.lower() in {"- none recorded yet.", "none recorded yet.", "- none."}:
            continue
        parsed_sections[current_section].append(line)

    return render_context_document(
        project_name=project_name,
        project_slug=project_slug,
        sections=parsed_sections,
        source_files=source_files,
        distillation_mode=provider,
        model=model,
    )


def _infer_project_name(inputs: list[Path], explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    first = Path(inputs[0]).expanduser().resolve()
    if first.is_dir():
        return first.name
    if first.parent.name not in {"", "."}:
        return first.parent.name
    return first.stem


def distill_memory(
    inputs: list[Path],
    output_path: Path | None = None,
    project_name: str | None = None,
    provider: str = "extractive",
    model: str | None = None,
    max_chars: int = 12000,
    chunk_chars: int = 48000,
    redact: bool = True,
    provider_instance: LLMProvider | None = None,
) -> DistillResult:
    """Distill transcript files into a structured 4-section project_prior_context.md."""
    raw_text, source_files = collect_input_texts(inputs)
    resolved_project = _infer_project_name(inputs, project_name)
    project_slug = slugify(resolved_project, fallback="project")

    secrets_redacted = 0
    if redact:
        raw_text, secrets_redacted = redact_secrets(raw_text)

    provider_key = provider.strip().lower()
    chunks_processed = 1

    if provider_key == "extractive" and provider_instance is None:
        final_md = distill_extractive(
            text=raw_text,
            project_name=resolved_project,
            project_slug=project_slug,
            source_files=source_files,
            max_chars=max_chars,
        )
        used_model: str | None = None
    else:
        llm = provider_instance or get_provider(provider_key, model=model)
        provider_key = llm.provider_name
        used_model = llm.model
        chunks = chunk_text(raw_text, chunk_chars=chunk_chars)
        chunks_processed = len(chunks)

        if len(chunks) == 1:
            user_prompt = (
                f"Project: {resolved_project} (`{project_slug}`)\n"
                f"Target maximum length: ~{max_chars} characters.\n\n"
                f"Source transcripts:\n\n{chunks[0]}"
            )
            llm_raw = llm.complete(_SYSTEM_PROMPT, user_prompt)
        else:
            partials: list[str] = []
            for idx, chunk in enumerate(chunks, start=1):
                chunk_prompt = (
                    f"Project: {resolved_project} (`{project_slug}`)\n"
                    f"Chunk {idx} of {len(chunks)}. Extract durable facts, decisions, "
                    "current state, constraints, and open questions into the 4 sections.\n\n"
                    f"{chunk}"
                )
                partials.append(llm.complete(_SYSTEM_PROMPT, chunk_prompt))

            reduce_prompt = (
                f"Project: {resolved_project} (`{project_slug}`)\n"
                f"Target maximum length: ~{max_chars} characters.\n\n"
                "Merge and deduplicate these partial summaries into one cohesive final "
                "4-section summary:\n\n" + "\n\n---\n\n".join(partials)
            )
            llm_raw = llm.complete(_SYSTEM_PROMPT, reduce_prompt)

        if redact:
            llm_raw, post_redacted = redact_secrets(llm_raw)
            secrets_redacted += post_redacted

        final_md = normalize_four_sections(
            raw_markdown=llm_raw,
            project_name=resolved_project,
            project_slug=project_slug,
            source_files=source_files,
            provider=provider_key,
            model=used_model,
        )

    out_file: Path | None = None
    if output_path is not None:
        out_file = Path(output_path).expanduser().resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(final_md, encoding="utf-8")

    return DistillResult(
        output_path=out_file,
        content=final_md,
        provider=provider_key,
        model=used_model,
        chunks_processed=chunks_processed,
        secrets_redacted=secrets_redacted,
        source_files=source_files,
    )
