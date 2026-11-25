"""Codex CLI session rollout (*.jsonl) parser and per-project Markdown converter."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory_bridge.utils import format_timestamp, slugify, truncate_text, utc_now_iso

_BOILERPLATE_BLOCK_RE = re.compile(
    r"<(?:environment_context|INSTRUCTIONS|user_instructions)>[\s\S]*?</(?:environment_context|INSTRUCTIONS|user_instructions)>",
    re.IGNORECASE,
)


@dataclass(slots=True)
class CodexTurn:
    """Single user or assistant turn extracted from a Codex rollout file."""

    role: str
    text: str
    timestamp: str


@dataclass(slots=True)
class CodexSession:
    """Parsed Codex session rollout with metadata and skipped line count."""

    session_id: str
    source_path: Path
    source_kind: str
    cwd: str | None
    started_at: str
    git_branch: str | None = None
    turns: list[CodexTurn] = field(default_factory=list)
    malformed_lines: int = 0


@dataclass(slots=True)
class CodexExportSummary:
    """Summary metrics produced by converting Codex rollouts."""

    sessions_scanned: int
    sessions_exported: int
    projects_written: int
    malformed_lines_skipped: int
    active_sessions: int
    archived_sessions: int
    output_dir: Path


def _clean_codex_text(text: str) -> str:
    cleaned = _BOILERPLATE_BLOCK_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _extract_content_blocks(content: Any) -> str:
    if isinstance(content, str):
        return _clean_codex_text(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                cleaned = _clean_codex_text(item)
                if cleaned:
                    parts.append(cleaned)
            elif isinstance(item, dict):
                block_type = str(item.get("type") or "")
                if block_type in {"input_text", "output_text", "text", ""}:
                    txt = item.get("text")
                    if isinstance(txt, str):
                        cleaned = _clean_codex_text(txt)
                        if cleaned:
                            parts.append(cleaned)
        return "\n\n".join(parts).strip()
    return ""


def _append_turn(turns: list[CodexTurn], role: str, text: str, timestamp: str) -> None:
    if not text:
        return
    if turns and turns[-1].role == role and turns[-1].text == text:
        return
    turns.append(CodexTurn(role=role, text=text, timestamp=timestamp))


def parse_rollout_file(
    path: Path,
    source_kind: str = "active",
    include_tool_calls: bool = False,
) -> CodexSession:
    """Parse a single Codex rollout-*.jsonl file without crashing on malformed lines."""
    session_id = path.stem
    cwd: str | None = None
    started_at = "unknown"
    git_branch: str | None = None
    turns: list[CodexTurn] = []
    malformed_lines = 0

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines += 1
                continue
            if not isinstance(record, dict):
                malformed_lines += 1
                continue

            rec_type = str(record.get("type") or "")
            rec_ts = format_timestamp(record.get("timestamp"))
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}

            if rec_type == "session_meta":
                meta = payload or record
                if meta.get("id"):
                    session_id = str(meta["id"])
                if meta.get("cwd"):
                    cwd = str(meta["cwd"])
                meta_ts = format_timestamp(meta.get("timestamp") or record.get("timestamp"))
                if meta_ts != "unknown":
                    started_at = meta_ts
                git_info = meta.get("git") if isinstance(meta.get("git"), dict) else {}
                if git_info.get("branch"):
                    git_branch = str(git_info["branch"])
                continue

            if started_at == "unknown" and rec_ts != "unknown":
                started_at = rec_ts

            if rec_type == "response_item":
                item_type = str(payload.get("type") or "")
                if item_type == "message":
                    role = str(payload.get("role") or "").lower()
                    if role in {"user", "assistant"}:
                        text = _extract_content_blocks(payload.get("content"))
                        _append_turn(turns, role, text, rec_ts)
                elif include_tool_calls and item_type in {"function_call", "custom_tool_call"}:
                    tool_name = str(payload.get("name") or "tool")
                    args = str(payload.get("arguments") or payload.get("input") or "").strip()
                    summary = f"[tool call `{tool_name}`] {truncate_text(args, 240)}".strip()
                    _append_turn(turns, "tool", summary, rec_ts)
                elif include_tool_calls and item_type in {"function_call_output", "custom_tool_call_output"}:
                    output = str(payload.get("output") or "").strip()
                    if output:
                        _append_turn(turns, "tool", f"[tool output] {truncate_text(output, 240)}", rec_ts)
                continue

            if rec_type == "event_msg":
                ev_type = str(payload.get("type") or "")
                if ev_type == "user_message":
                    text = _clean_codex_text(str(payload.get("message") or payload.get("text") or ""))
                    _append_turn(turns, "user", text, rec_ts)
                elif ev_type == "agent_message":
                    text = _clean_codex_text(str(payload.get("message") or payload.get("text") or ""))
                    _append_turn(turns, "assistant", text, rec_ts)
                continue

            if rec_type == "message":
                role = str(record.get("role") or "").lower()
                if role in {"user", "assistant"}:
                    text = _extract_content_blocks(record.get("content"))
                    _append_turn(turns, role, text, rec_ts)

    return CodexSession(
        session_id=session_id,
        source_path=path,
        source_kind=source_kind,
        cwd=cwd,
        started_at=started_at,
        git_branch=git_branch,
        turns=turns,
        malformed_lines=malformed_lines,
    )


def resolve_project_slugs(cwds: list[str | None]) -> dict[str | None, str]:
    """Map normalized working directories to unique kebab-case project slugs."""
    normalized_by_raw: dict[str | None, str | None] = {}
    unique_cwds: list[str] = []
    seen_norm: set[str] = set()

    for raw in cwds:
        if not raw or not raw.strip():
            normalized_by_raw[raw] = None
            continue
        norm = str(Path(raw.strip()))
        normalized_by_raw[raw] = norm
        if norm not in seen_norm:
            seen_norm.add(norm)
            unique_cwds.append(norm)

    base_groups: dict[str, list[str]] = {}
    for norm in unique_cwds:
        base = slugify(Path(norm).name, fallback="root")
        base_groups.setdefault(base, []).append(norm)

    norm_to_slug: dict[str, str] = {}
    used_slugs: set[str] = {"unknown-project"}

    for base, paths in sorted(base_groups.items()):
        if len(paths) == 1:
            candidate = base
            if candidate in used_slugs:
                digest = hashlib.sha1(paths[0].encode("utf-8")).hexdigest()[:6]
                candidate = f"{base}-{digest}"
            used_slugs.add(candidate)
            norm_to_slug[paths[0]] = candidate
            continue

        for norm in sorted(paths):
            parent_name = slugify(Path(norm).parent.name, fallback="")
            candidate = f"{parent_name}-{base}" if parent_name else base
            if candidate in used_slugs:
                digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:6]
                candidate = f"{candidate}-{digest}"
            used_slugs.add(candidate)
            norm_to_slug[norm] = candidate

    result: dict[str | None, str] = {}
    for raw, norm in normalized_by_raw.items():
        if norm is None:
            result[raw] = "unknown-project"
        else:
            result[raw] = norm_to_slug[norm]
    return result


def _discover_rollout_files(
    sessions_dir: Path | None,
    archived_dir: Path | None,
    extra_dirs: list[Path] | None,
) -> list[tuple[Path, str]]:
    search_roots: list[tuple[Path, str]] = []
    if sessions_dir is not None:
        search_roots.append((Path(sessions_dir).expanduser(), "active"))
    if archived_dir is not None:
        search_roots.append((Path(archived_dir).expanduser(), "archived"))
    for extra in extra_dirs or []:
        search_roots.append((Path(extra).expanduser(), "extra"))

    discovered: list[tuple[Path, str]] = []
    seen_paths: set[Path] = set()
    for root, kind in search_roots:
        if not root.exists() or not root.is_dir():
            continue
        for file_path in sorted(root.rglob("rollout-*.jsonl")):
            if not file_path.is_file():
                continue
            resolved = file_path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            discovered.append((file_path, kind))
    return discovered


def _render_project_index(project_slug: str, sessions: list[CodexSession]) -> str:
    cwds = sorted({s.cwd for s in sessions if s.cwd})
    lines = [
        f"# Codex Sessions — {project_slug}",
        "",
        f"- **Project Slug:** `{project_slug}`",
        f"- **Working Directories:** {', '.join(f'`{c}`' for c in cwds) if cwds else '`unknown`'}",
        f"- **Sessions:** {len(sessions)}",
        f"- **Exported:** {utc_now_iso()}",
        "",
        "| Started (UTC) | Source | Session ID | Branch | Turns | Skipped Lines |",
        "| :--- | :--- | :--- | :--- | ---: | ---: |",
    ]
    for sess in sessions:
        branch = sess.git_branch or "-"
        lines.append(
            f"| {sess.started_at} | `{sess.source_kind}` | `{sess.session_id}` | "
            f"`{branch}` | {len(sess.turns)} | {sess.malformed_lines} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_codex_project_memory(
    project_slug: str,
    sessions: list[CodexSession],
    max_chars_per_turn: int,
) -> str:
    cwds = sorted({s.cwd for s in sessions if s.cwd})
    lines = [
        "---",
        f"project: {project_slug}",
        f"slug: {project_slug}",
        f"sessions: {len(sessions)}",
        f"exported_at: {utc_now_iso()}",
        "---",
        "",
        f"# {project_slug} — Codex Project Memory",
        "",
        f"- **Working Directory:** `{cwds[0]}`" if cwds else "- **Working Directory:** `unknown`",
        "",
    ]
    for sess in sessions:
        lines.extend(
            [
                f"## Session `{sess.session_id}` ({sess.started_at})",
                "",
                f"- **Source:** `{sess.source_kind}` | **CWD:** `{sess.cwd or 'unknown'}`"
                + (f" | **Branch:** `{sess.git_branch}`" if sess.git_branch else ""),
                f"- **Turns:** {len(sess.turns)}",
                "",
            ]
        )
        for turn in sess.turns:
            lines.append(f"### {turn.role.capitalize()} ({turn.timestamp})")
            lines.append("")
            lines.append(truncate_text(turn.text, max_chars_per_turn))
            lines.append("")
    return "\n".join(lines)


def _render_raw_session(sess: CodexSession) -> str:
    lines = [
        f"# Codex Session `{sess.session_id}`",
        "",
        f"- **Source File:** `{sess.source_path}`",
        f"- **Source Kind:** `{sess.source_kind}`",
        f"- **CWD:** `{sess.cwd or 'unknown'}`",
        f"- **Started:** {sess.started_at}",
        f"- **Malformed Lines Skipped:** {sess.malformed_lines}",
        "",
    ]
    for turn in sess.turns:
        lines.append(f"## {turn.role.capitalize()} ({turn.timestamp})")
        lines.append("")
        lines.append(turn.text)
        lines.append("")
    return "\n".join(lines)


def convert_codex_sessions(
    output_dir: Path,
    sessions_dir: Path | None = None,
    archived_dir: Path | None = None,
    extra_dirs: list[Path] | None = None,
    include_raw: bool = False,
    include_tool_calls: bool = False,
    max_chars_per_turn: int = 1200,
) -> CodexExportSummary:
    """Scan Codex rollout files and write compact per-project Markdown memory."""
    if sessions_dir is None and archived_dir is None and not extra_dirs:
        sessions_dir = Path.home() / ".codex" / "sessions"
        archived_dir = Path.home() / ".codex" / "archived_sessions"

    discovered = _discover_rollout_files(sessions_dir, archived_dir, extra_dirs)
    out_root = Path(output_dir).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    parsed_sessions: list[CodexSession] = []
    malformed_total = 0
    active_count = 0
    archived_count = 0

    for file_path, kind in discovered:
        session = parse_rollout_file(
            file_path,
            source_kind=kind,
            include_tool_calls=include_tool_calls,
        )
        malformed_total += session.malformed_lines
        if kind == "active":
            active_count += 1
        elif kind == "archived":
            archived_count += 1
        if session.turns:
            parsed_sessions.append(session)

    cwd_to_slug = resolve_project_slugs([s.cwd for s in parsed_sessions])
    grouped: dict[str, list[CodexSession]] = {}
    for session in parsed_sessions:
        slug = cwd_to_slug.get(session.cwd, "unknown-project")
        grouped.setdefault(slug, []).append(session)

    project_rows: list[tuple[str, int, int, str]] = []
    for slug, sessions in sorted(grouped.items()):
        sessions.sort(key=lambda s: (s.started_at, s.session_id))
        proj_dir = out_root / slug
        proj_dir.mkdir(parents=True, exist_ok=True)

        (proj_dir / "INDEX.md").write_text(
            _render_project_index(slug, sessions),
            encoding="utf-8",
        )
        (proj_dir / "CODEX_PROJECT_MEMORY.md").write_text(
            _render_codex_project_memory(slug, sessions, max_chars_per_turn=max_chars_per_turn),
            encoding="utf-8",
        )

        if include_raw:
            raw_dir = proj_dir / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            for sess in sessions:
                filename = f"{slugify(sess.session_id, fallback='session')}.md"
                (raw_dir / filename).write_text(_render_raw_session(sess), encoding="utf-8")

        total_turns = sum(len(s.turns) for s in sessions)
        sample_cwd = next((s.cwd for s in sessions if s.cwd), "unknown")
        project_rows.append((slug, len(sessions), total_turns, sample_cwd))

    index_lines = [
        "# Codex Sessions Memory Index",
        "",
        f"- **Exported At:** {utc_now_iso()}",
        f"- **Rollout Files Scanned:** {len(discovered)} (active: {active_count}, archived: {archived_count})",
        f"- **Sessions Exported (with turns):** {len(parsed_sessions)}",
        f"- **Projects Written:** {len(grouped)}",
        f"- **Malformed/Truncated JSONL Lines Skipped:** {malformed_total}",
        "",
        "| Project Slug | Sessions | Turns | Sample CWD | Memory File |",
        "| :--- | ---: | ---: | :--- | :--- |",
    ]
    for slug, sess_count, turn_count, sample_cwd in project_rows:
        safe_cwd = sample_cwd.replace("|", "\\|")
        index_lines.append(
            f"| `{slug}` | {sess_count} | {turn_count} | `{safe_cwd}` | `{slug}/CODEX_PROJECT_MEMORY.md` |"
        )
    index_lines.append("")
    (out_root / "INDEX.md").write_text("\n".join(index_lines), encoding="utf-8")

    return CodexExportSummary(
        sessions_scanned=len(discovered),
        sessions_exported=len(parsed_sessions),
        projects_written=len(grouped),
        malformed_lines_skipped=malformed_total,
        active_sessions=active_count,
        archived_sessions=archived_count,
        output_dir=out_root,
    )
