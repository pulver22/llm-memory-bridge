"""Zero-cost deterministic extractive compactor for project_prior_context.md."""

from __future__ import annotations

import re

from memory_bridge.utils import utc_now_iso

REQUIRED_SECTIONS: tuple[str, ...] = (
    "Finalised Decisions & Architecture",
    "Active Work & Current State",
    "Key Facts, Constraints & Parameters",
    "Open Questions & Next Steps",
)

_FILLER_RE = re.compile(
    r"^(?:thanks|thank you|sounds good|ok(?:ay)?|got it|sure|let me check|great|cool|hello|hi)\b[.!]*$",
    re.IGNORECASE,
)
_METADATA_BULLET_RE = re.compile(
    r"^\*\*?(?:conversation id|created|updated|active turns|source|cwd|branch|turns|group|category)\b",
    re.IGNORECASE,
)

_SECTION_CUES: dict[str, tuple[str, ...]] = {
    "Finalised Decisions & Architecture": (
        "decided",
        "decision",
        "architecture",
        "chosen",
        "adopted",
        "migrated",
        "stack",
        "schema",
        "design",
        "standardize",
        "standardised",
        "standardized",
        "use ",
        "using ",
        "replace ",
        "replaced",
        "selected",
        "agreed",
        "protocol",
        "layout",
    ),
    "Active Work & Current State": (
        "currently",
        "in progress",
        "implementing",
        "implemented",
        "working on",
        "passing",
        "failing",
        "branch",
        "status",
        "completed",
        "deployed",
        "wip",
        "built",
        "added",
        "fixed",
        "refactor",
        "shipping",
        "current state",
    ),
    "Key Facts, Constraints & Parameters": (
        "must",
        "never",
        "always",
        "constraint",
        "limit",
        "port",
        "env",
        "version",
        "timeout",
        "requires",
        "required",
        "config",
        "parameter",
        "budget",
        "path",
        "python",
        "default",
        "rate limit",
        "schema",
        "max ",
        "min ",
    ),
    "Open Questions & Next Steps": (
        "?",
        "todo",
        "tbd",
        "next",
        "open question",
        "blocked",
        "blocker",
        "investigate",
        "follow up",
        "follow-up",
        "remaining",
        "pending",
        "should we",
        "need to",
        "plan to",
        "verify",
    ),
}


def _strip_frontmatter(text: str) -> str:
    stripped = text.lstrip()
    if stripped.startswith("---\n"):
        end = stripped.find("\n---\n", 4)
        if end != -1:
            return stripped[end + 5 :]
    return text


def _clean_candidate(line: str) -> str:
    cleaned = line.strip()
    cleaned = re.sub(r"^[-*+]\s+", "", cleaned)
    cleaned = re.sub(r"^\d+\.\s+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _extract_candidates(text: str) -> list[str]:
    body = _strip_frontmatter(text)
    candidates: list[str] = []
    in_code_fence = False

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence or not line:
            continue
        if line.startswith("#") or line.startswith("|") or line.startswith("---"):
            continue
        if line.startswith("> *[Skipped"):
            continue

        cleaned = _clean_candidate(line)
        if len(cleaned) < 16:
            continue
        if _FILLER_RE.match(cleaned) or _METADATA_BULLET_RE.match(cleaned):
            continue

        if len(cleaned) > 260:
            sentences = re.split(r"(?<=[.!?])\s+", cleaned)
            for sent in sentences:
                sent = sent.strip()
                if len(sent) >= 16 and not _FILLER_RE.match(sent):
                    candidates.append(sent[:260].rstrip())
        else:
            candidates.append(cleaned)

    return candidates


def _score_section(statement: str, position_ratio: float) -> tuple[str, float]:
    lower = statement.lower()
    scores: dict[str, float] = {sec: 0.0 for sec in REQUIRED_SECTIONS}

    for section, cues in _SECTION_CUES.items():
        for cue in cues:
            if cue in lower:
                scores[section] += 2.0 if len(cue) > 4 else 1.5

    if "?" in statement:
        scores["Open Questions & Next Steps"] += 3.5
    if re.search(r"\b\d+(?:\.\d+)+\b", statement) or "`" in statement:
        scores["Key Facts, Constraints & Parameters"] += 1.0

    # Recency boost for active work and next steps
    scores["Active Work & Current State"] += position_ratio * 1.2
    scores["Open Questions & Next Steps"] += position_ratio * 0.9

    best_section = max(REQUIRED_SECTIONS, key=lambda sec: scores[sec])
    best_score = scores[best_section]

    if best_score < 1.5:
        if position_ratio >= 0.6:
            return ("Active Work & Current State", 1.0 + position_ratio)
        return ("Key Facts, Constraints & Parameters", 0.8 + position_ratio * 0.5)

    return (best_section, best_score + position_ratio * 0.25)


def render_context_document(
    project_name: str,
    project_slug: str,
    sections: dict[str, list[str]],
    source_files: list[str],
    distillation_mode: str,
    model: str | None = None,
) -> str:
    """Render the canonical 4-section project_prior_context.md document."""
    lines = [
        "---",
        f"project: {project_name}",
        f"slug: {project_slug}",
        f"updated_at: {utc_now_iso()}",
        f"distillation_mode: {distillation_mode}",
    ]
    if model:
        lines.append(f"model: {model}")
    if source_files:
        lines.append("sources:")
        for src in source_files:
            lines.append(f"  - {src}")
    lines.extend(
        [
            "---",
            "",
            f"# {project_name} — Prior Context",
            "",
        ]
    )

    for section in REQUIRED_SECTIONS:
        lines.append(f"## {section}")
        lines.append("")
        items = sections.get(section) or []
        if not items:
            lines.append("- None recorded yet.")
        else:
            for item in items:
                clean = item.strip()
                if not clean.startswith("- "):
                    clean = f"- {clean}"
                lines.append(clean)
        lines.append("")

    return "\n".join(lines)


def distill_extractive(
    text: str,
    project_name: str,
    project_slug: str,
    source_files: list[str],
    max_chars: int = 12000,
    max_items_per_section: int = 15,
) -> str:
    """Deterministically condense transcripts into the 4-section context file."""
    candidates = _extract_candidates(text)
    bucketed: dict[str, list[tuple[float, int, str]]] = {sec: [] for sec in REQUIRED_SECTIONS}
    seen_fingerprints: set[str] = set()

    total = max(1, len(candidates) - 1)
    for idx, stmt in enumerate(candidates):
        fingerprint = re.sub(r"[^a-z0-9]+", "", stmt.lower())
        if not fingerprint or fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        pos_ratio = idx / total
        section, score = _score_section(stmt, pos_ratio)
        bucketed[section].append((score, idx, stmt))

    selected: dict[str, list[str]] = {}
    for section in REQUIRED_SECTIONS:
        ranked = sorted(bucketed[section], key=lambda item: (-item[0], item[1]))
        chosen = sorted(ranked[:max_items_per_section], key=lambda item: item[1])
        selected[section] = [item[2] for item in chosen]

    rendered = render_context_document(
        project_name=project_name,
        project_slug=project_slug,
        sections=selected,
        source_files=source_files,
        distillation_mode="extractive",
    )

    if max_chars > 0 and len(rendered) > max_chars:
        # Trim least-scored items evenly across sections until within max_chars
        current_cap = max_items_per_section
        while len(rendered) > max_chars and current_cap > 1:
            current_cap -= 1
            for section in REQUIRED_SECTIONS:
                ranked = sorted(bucketed[section], key=lambda item: (-item[0], item[1]))
                chosen = sorted(ranked[:current_cap], key=lambda item: item[1])
                selected[section] = [item[2] for item in chosen]
            rendered = render_context_document(
                project_name=project_name,
                project_slug=project_slug,
                sections=selected,
                source_files=source_files,
                distillation_mode="extractive",
            )
    return rendered
