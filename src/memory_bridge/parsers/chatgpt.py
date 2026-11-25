"""ChatGPT export archive parser and compact Markdown exporter."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory_bridge.utils import (
    format_timestamp,
    slugify,
    strip_chatgpt_artifacts,
    truncate_text,
    utc_now_iso,
)

_IGNORED_CONTENT_TYPES = frozenset(
    {
        "thoughts",
        "reasoning_recap",
        "model_editable_context",
        "user_editable_context",
        "system_error",
    }
)
_NATURAL_NUM_RE = re.compile(r"(\d+)")


@dataclass(slots=True)
class ChatTurn:
    """Single message turn on the active ChatGPT conversation chain."""

    role: str
    text: str
    timestamp: str
    node_id: str


@dataclass(slots=True)
class ParsedConversation:
    """Normalized ChatGPT conversation extracted from export data."""

    conv_id: str
    title: str
    category: str
    group_id: str
    group_name: str
    group_slug: str
    create_time: float | None
    update_time: float | None
    turns: list[ChatTurn] = field(default_factory=list)
    total_mapping_nodes: int = 0


@dataclass(slots=True)
class ExportSummary:
    """Summary metrics produced by a ChatGPT export run."""

    total_conversations: int
    exported_conversations: int
    groups_written: dict[str, int]
    output_dir: Path


def _natural_sort_key(name: str) -> list[int | str]:
    parts = _NATURAL_NUM_RE.split(name)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _parse_json_conversations(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if "mapping" in payload or "title" in payload:
            return [payload]
        if isinstance(payload.get("conversations"), list):
            return [item for item in payload["conversations"] if isinstance(item, dict)]
    return []


def load_conversations(input_path: Path) -> list[dict[str, Any]]:
    """Load and deduplicate ChatGPT conversations from a zip, directory, or JSON file."""
    path = Path(input_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"ChatGPT export input does not exist: {path}")

    raw_conversations: list[dict[str, Any]] = []

    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            members = sorted(
                (
                    name
                    for name in zf.namelist()
                    if not name.endswith("/")
                    and Path(name).name.startswith("conversations")
                    and Path(name).suffix.lower() == ".json"
                ),
                key=_natural_sort_key,
            )
            if not members:
                raise ValueError(f"No conversations*.json files found inside zip archive: {path}")
            for member in members:
                with zf.open(member) as handle:
                    payload = json.loads(handle.read().decode("utf-8"))
                raw_conversations.extend(_parse_json_conversations(payload))
    elif path.is_dir():
        files = sorted(
            (p for p in path.glob("conversations*.json") if p.is_file()),
            key=lambda p: _natural_sort_key(p.name),
        )
        if not files:
            files = sorted(
                (p for p in path.rglob("conversations*.json") if p.is_file()),
                key=lambda p: _natural_sort_key(str(p)),
            )
        if not files:
            raise ValueError(f"No conversations*.json files found in directory: {path}")
        for json_file in files:
            payload = json.loads(json_file.read_text(encoding="utf-8"))
            raw_conversations.extend(_parse_json_conversations(payload))
    elif path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_conversations.extend(_parse_json_conversations(payload))
    else:
        raise ValueError(f"Unsupported input path: {path}")

    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, conv in enumerate(raw_conversations):
        cid = str(conv.get("id") or conv.get("conversation_id") or f"anon-{idx}")
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        deduped.append(conv)
    return deduped


def classify_conversation(
    conv: dict[str, Any],
    names_map: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    """Classify a conversation into (category, group_id, group_name)."""
    gizmo_id = conv.get("gizmo_id")
    gizmo_type = str(conv.get("gizmo_type") or "").lower()
    origin = str(conv.get("conversation_origin") or "").lower()
    metadata = conv.get("metadata") if isinstance(conv.get("metadata"), dict) else {}
    meta_source = str(metadata.get("source") or "").lower()

    if (
        gizmo_type == "codex"
        or origin == "codex"
        or bool(conv.get("is_codex"))
        or bool(conv.get("codex_task_id"))
        or meta_source == "codex"
    ):
        return ("codex", "codex", "Codex Exports")

    gid_str = str(gizmo_id).strip() if isinstance(gizmo_id, str) else ""
    if gid_str.startswith("g-p-") or gizmo_type == "snorlax":
        group_id = gid_str or "project-unnamed"
        display_name = (
            (names_map or {}).get(group_id)
            or conv.get("gizmo_title")
            or conv.get("project_name")
            or group_id
        )
        return ("projects", group_id, str(display_name))

    if gid_str.startswith("g-"):
        display_name = (
            (names_map or {}).get(gid_str)
            or conv.get("gizmo_title")
            or gid_str
        )
        return ("gpts", gid_str, str(display_name))

    return ("standalone", "standalone", "Standalone Chats")


def _extract_message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if not isinstance(content, dict):
        return ""
    content_type = str(content.get("content_type") or "")
    if content_type in _IGNORED_CONTENT_TYPES:
        return ""

    parts = content.get("parts")
    extracted: list[str] = []
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, str):
                cleaned = strip_chatgpt_artifacts(part)
                if cleaned:
                    extracted.append(cleaned)
            elif isinstance(part, dict):
                part_text = part.get("text")
                if isinstance(part_text, str) and part_text.strip():
                    extracted.append(strip_chatgpt_artifacts(part_text))
                else:
                    part_type = str(part.get("content_type") or part.get("type") or "attachment")
                    extracted.append(f"[attachment: {part_type}]")
    elif isinstance(content.get("text"), str):
        cleaned = strip_chatgpt_artifacts(content["text"])
        if cleaned:
            extracted.append(cleaned)

    return "\n\n".join(extracted).strip()


def _fallback_leaf_node_id(mapping: dict[str, Any]) -> str | None:
    if not mapping:
        return None
    best_id: str | None = None
    best_score = (-1, -1.0)
    for node_id, node in mapping.items():
        if not isinstance(node, dict):
            continue
        children = node.get("children") or []
        valid_children = [c for c in children if c in mapping]
        is_leaf = 1 if not valid_children else 0
        msg = node.get("message")
        ts = _coerce_float(msg.get("create_time")) if isinstance(msg, dict) else None
        score = (is_leaf, ts if ts is not None else -1.0)
        if score > best_score:
            best_score = score
            best_id = node_id
    return best_id


def extract_active_messages(
    conv: dict[str, Any],
    include_tools: bool = False,
) -> list[ChatTurn]:
    """Walk only the active conversation chain from current_node back to root."""
    mapping = conv.get("mapping")
    if not isinstance(mapping, dict) or not mapping:
        return []

    node_id = conv.get("current_node")
    if not isinstance(node_id, str) or node_id not in mapping:
        node_id = _fallback_leaf_node_id(mapping)

    chain_ids: list[str] = []
    visited: set[str] = set()
    while isinstance(node_id, str) and node_id in mapping and node_id not in visited:
        visited.add(node_id)
        chain_ids.append(node_id)
        node = mapping[node_id]
        if not isinstance(node, dict):
            break
        node_id = node.get("parent")

    chain_ids.reverse()
    allowed_roles = {"user", "assistant", "tool"} if include_tools else {"user", "assistant"}

    turns: list[ChatTurn] = []
    for cid in chain_ids:
        node = mapping.get(cid)
        if not isinstance(node, dict):
            continue
        msg = node.get("message")
        if not isinstance(msg, dict):
            continue
        metadata = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
        if metadata.get("is_visually_hidden_from_conversation"):
            continue
        author = msg.get("author") if isinstance(msg.get("author"), dict) else {}
        role = str(author.get("role") or "").lower()
        if role not in allowed_roles:
            continue
        text = _extract_message_text(msg)
        if not text:
            continue
        ts = format_timestamp(_coerce_float(msg.get("create_time")))
        turns.append(ChatTurn(role=role, text=text, timestamp=ts, node_id=cid))
    return turns


def _load_names_map(names_map_path: Path | None) -> dict[str, str]:
    if names_map_path is None:
        return {}
    path = Path(names_map_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Names map file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Names map must be a JSON object mapping ID -> name: {path}")
    return {str(k): str(v) for k, v in data.items()}


def _group_output_dir(output_dir: Path, category: str, group_slug: str) -> Path:
    if category in {"projects", "gpts"}:
        return output_dir / category / group_slug
    return output_dir / category


def _render_group_index(
    group_name: str,
    category: str,
    group_id: str,
    conversations: list[ParsedConversation],
) -> str:
    lines = [
        f"# {group_name} — Conversation Index",
        "",
        f"- **Category:** `{category}`",
        f"- **Group ID:** `{group_id}`",
        f"- **Conversations:** {len(conversations)}",
        f"- **Exported:** {utc_now_iso()}",
        "",
        "| Date (UTC) | Title | Active Turns | Pruned Nodes |",
        "| :--- | :--- | ---: | ---: |",
    ]
    for conv in conversations:
        date_str = format_timestamp(conv.update_time or conv.create_time)
        safe_title = conv.title.replace("|", "\\|")
        pruned = max(0, conv.total_mapping_nodes - len(conv.turns))
        lines.append(f"| {date_str} | {safe_title} | {len(conv.turns)} | {pruned} |")
    lines.append("")
    return "\n".join(lines)


def _render_group_memory(
    group_name: str,
    category: str,
    group_slug: str,
    conversations: list[ParsedConversation],
    max_chars_per_turn: int,
    max_turns_per_chat: int,
) -> str:
    lines = [
        "---",
        f"group: {group_name}",
        f"slug: {group_slug}",
        f"category: {category}",
        f"conversations: {len(conversations)}",
        f"exported_at: {utc_now_iso()}",
        "---",
        "",
        f"# {group_name} — Project Memory",
        "",
    ]
    for conv in conversations:
        created = format_timestamp(conv.create_time)
        updated = format_timestamp(conv.update_time)
        lines.extend(
            [
                f"## {conv.title}",
                "",
                f"- **Conversation ID:** `{conv.conv_id}`",
                f"- **Created:** {created} | **Updated:** {updated}",
                f"- **Active Turns:** {len(conv.turns)}",
                "",
            ]
        )
        selected_turns = conv.turns
        if max_turns_per_chat > 0 and len(conv.turns) > max_turns_per_chat:
            omitted = len(conv.turns) - max_turns_per_chat
            lines.append(f"> *[Skipped {omitted} earlier turns; showing last {max_turns_per_chat}]*")
            lines.append("")
            selected_turns = conv.turns[-max_turns_per_chat:]

        for turn in selected_turns:
            role_label = turn.role.capitalize()
            body = truncate_text(turn.text, max_chars_per_turn)
            lines.append(f"### {role_label} ({turn.timestamp})")
            lines.append("")
            lines.append(body)
            lines.append("")
    return "\n".join(lines)


def _render_raw_conversation(conv: ParsedConversation) -> str:
    lines = [
        f"# {conv.title}",
        "",
        f"- **Conversation ID:** `{conv.conv_id}`",
        f"- **Group:** `{conv.category}/{conv.group_slug}`",
        f"- **Created:** {format_timestamp(conv.create_time)}",
        f"- **Updated:** {format_timestamp(conv.update_time)}",
        "",
    ]
    for turn in conv.turns:
        lines.append(f"## {turn.role.capitalize()} ({turn.timestamp})")
        lines.append("")
        lines.append(turn.text)
        lines.append("")
    return "\n".join(lines)


def export_chatgpt(
    input_path: Path,
    output_dir: Path,
    include_raw: bool = False,
    include_tools: bool = False,
    max_chars_per_turn: int = 1200,
    max_turns_per_chat: int = 0,
    names_map_path: Path | None = None,
    group_filter: str = "all",
) -> ExportSummary:
    """Parse a ChatGPT export and write grouped compact Markdown memory files."""
    valid_filters = {"all", "projects", "gpts", "codex", "standalone"}
    if group_filter not in valid_filters:
        raise ValueError(f"Invalid group filter '{group_filter}'. Choose from {sorted(valid_filters)}")

    names_map = _load_names_map(names_map_path)
    raw_conversations = load_conversations(input_path)
    out_root = Path(output_dir).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    grouped: dict[tuple[str, str], list[ParsedConversation]] = {}
    exported_count = 0

    for idx, conv in enumerate(raw_conversations):
        category, group_id, group_name = classify_conversation(conv, names_map=names_map)
        if group_filter != "all" and category != group_filter:
            continue
        turns = extract_active_messages(conv, include_tools=include_tools)
        if not turns:
            continue

        conv_id = str(conv.get("id") or conv.get("conversation_id") or f"conv-{idx}")
        title = str(conv.get("title") or "").strip() or f"Untitled Conversation ({conv_id[:8]})"
        group_slug = slugify(group_name, fallback=slugify(group_id, fallback=category))
        mapping = conv.get("mapping") if isinstance(conv.get("mapping"), dict) else {}

        parsed = ParsedConversation(
            conv_id=conv_id,
            title=title,
            category=category,
            group_id=group_id,
            group_name=group_name,
            group_slug=group_slug,
            create_time=_coerce_float(conv.get("create_time")),
            update_time=_coerce_float(conv.get("update_time")),
            turns=turns,
            total_mapping_nodes=len(mapping),
        )
        grouped.setdefault((category, group_slug), []).append(parsed)
        exported_count += 1

    groups_written: dict[str, int] = {}
    manifest_groups: list[dict[str, Any]] = []

    for (category, group_slug), convs in sorted(grouped.items()):
        convs.sort(key=lambda c: (c.create_time or 0.0, c.update_time or 0.0, c.conv_id))
        group_dir = _group_output_dir(out_root, category, group_slug)
        group_dir.mkdir(parents=True, exist_ok=True)

        group_name = convs[0].group_name
        group_id = convs[0].group_id

        (group_dir / "INDEX.md").write_text(
            _render_group_index(group_name, category, group_id, convs),
            encoding="utf-8",
        )
        (group_dir / "PROJECT_MEMORY.md").write_text(
            _render_group_memory(
                group_name=group_name,
                category=category,
                group_slug=group_slug,
                conversations=convs,
                max_chars_per_turn=max_chars_per_turn,
                max_turns_per_chat=max_turns_per_chat,
            ),
            encoding="utf-8",
        )

        if include_raw:
            raw_dir = group_dir / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            for conv in convs:
                short_id = slugify(conv.conv_id[:8], fallback="chat")
                filename = f"{slugify(conv.title, fallback='chat')}-{short_id}.md"
                (raw_dir / filename).write_text(_render_raw_conversation(conv), encoding="utf-8")

        rel_dir = str(group_dir.relative_to(out_root))
        groups_written[rel_dir] = len(convs)
        manifest_groups.append(
            {
                "category": category,
                "group_id": group_id,
                "group_name": group_name,
                "group_slug": group_slug,
                "path": rel_dir,
                "conversations": len(convs),
                "total_turns": sum(len(c.turns) for c in convs),
            }
        )

    index_lines = [
        "# ChatGPT Memory Export Index",
        "",
        f"- **Source:** `{Path(input_path).name}`",
        f"- **Exported At:** {utc_now_iso()}",
        f"- **Total Input Conversations:** {len(raw_conversations)}",
        f"- **Exported Conversations (with active turns):** {exported_count}",
        f"- **Groups Written:** {len(manifest_groups)}",
        "",
        "| Category | Group | Conversations | Turns | Output Path |",
        "| :--- | :--- | ---: | ---: | :--- |",
    ]
    for item in manifest_groups:
        safe_name = str(item["group_name"]).replace("|", "\\|")
        index_lines.append(
            f"| `{item['category']}` | {safe_name} | {item['conversations']} | "
            f"{item['total_turns']} | `{item['path']}/PROJECT_MEMORY.md` |"
        )
    index_lines.append("")
    (out_root / "INDEX.md").write_text("\n".join(index_lines), encoding="utf-8")

    manifest = {
        "exported_at": utc_now_iso(),
        "total_conversations": len(raw_conversations),
        "exported_conversations": exported_count,
        "groups": manifest_groups,
    }
    (out_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return ExportSummary(
        total_conversations=len(raw_conversations),
        exported_conversations=exported_count,
        groups_written=groups_written,
        output_dir=out_root,
    )
