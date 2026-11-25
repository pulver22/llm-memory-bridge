"""Synthetic, anonymized pytest fixtures for llm-memory-bridge."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest


def _make_node(
    node_id: str,
    parent: str | None,
    children: list[str],
    role: str | None = None,
    parts: list[Any] | None = None,
    create_time: float | None = 1760000000.0,
    hidden: bool = False,
    content_type: str = "text",
) -> dict[str, Any]:
    if role is None:
        message = None
    else:
        message = {
            "id": node_id,
            "author": {"role": role},
            "create_time": create_time,
            "content": {"content_type": content_type, "parts": parts or []},
            "metadata": {"is_visually_hidden_from_conversation": hidden},
        }
    return {
        "id": node_id,
        "parent": parent,
        "children": children,
        "message": message,
    }


@pytest.fixture()
def synthetic_chatgpt_conversations() -> list[dict[str, Any]]:
    """Return synthetic ChatGPT conversations covering branching, Projects, GPTs, Codex, and cycles."""
    branching_project_conv = {
        "id": "conv-proj-1001",
        "title": "Service Architecture Design",
        "create_time": 1760000000.0,
        "update_time": 1760000500.0,
        "gizmo_id": "g-p-alpha123",
        "gizmo_title": "Alpha Platform",
        "current_node": "n_asst_final",
        "mapping": {
            "n_root": _make_node("n_root", None, ["n_sys"]),
            "n_sys": _make_node(
                "n_sys",
                "n_root",
                ["n_user_1"],
                role="system",
                parts=["Internal system prompt should be hidden"],
                hidden=True,
            ),
            "n_user_1": _make_node(
                "n_user_1",
                "n_sys",
                ["n_asst_abandoned", "n_asst_active"],
                role="user",
                parts=[
                    "Should we use SQLite or Postgres for the alpha worker?",
                    {"content_type": "image_asset_pointer", "asset_pointer": "file-img-001"},
                ],
                create_time=1760000050.0,
            ),
            "n_asst_abandoned": _make_node(
                "n_asst_abandoned",
                "n_user_1",
                [],
                role="assistant",
                parts=["ABANDONED_BRANCH: Recommend MongoDB instead."],
                create_time=1760000080.0,
            ),
            "n_asst_active": _make_node(
                "n_asst_active",
                "n_user_1",
                ["n_tool", "n_asst_final"],
                role="assistant",
                parts=[
                    "We decided to standardize on PostgreSQL 16 with Alembic migrations\ue200cite\ue202turn0\ue201."
                ],
                create_time=1760000100.0,
            ),
            "n_tool": _make_node(
                "n_tool",
                "n_asst_active",
                [],
                role="tool",
                parts=["TOOL_PAYLOAD: schema check passed"],
                create_time=1760000110.0,
            ),
            "n_asst_final": _make_node(
                "n_asst_final",
                "n_asst_active",
                [],
                role="assistant",
                parts=["ACTIVE_LEAF_CONFIRMED: Connection pool max_size is 20."],
                create_time=1760000150.0,
            ),
        },
    }

    custom_gpt_conv = {
        "id": "conv-gpt-2002",
        "title": "Release Checklist Helper",
        "create_time": 1760001000.0,
        "update_time": 1760001200.0,
        "gizmo_id": "g-writer999",
        "current_node": "g2",
        "mapping": {
            "g1": _make_node("g1", None, ["g2"], role="user", parts=["Draft release checklist."]),
            "g2": _make_node(
                "g2",
                "g1",
                [],
                role="assistant",
                parts=["Include MIT license and synthetic test fixtures only."],
            ),
        },
    }

    codex_export_conv = {
        "id": "conv-codex-3003",
        "title": "CLI Refactor Task",
        "create_time": 1760002000.0,
        "update_time": 1760002100.0,
        "gizmo_type": "codex",
        "current_node": "c2",
        "mapping": {
            "c1": _make_node("c1", None, ["c2"], role="user", parts=["Add --group filter to export."]),
            "c2": _make_node("c2", "c1", [], role="assistant", parts=["Implemented --group filter."]),
        },
    }

    cyclic_standalone_conv = {
        "id": "conv-std-4004",
        "title": "Standalone Cyclic Guard",
        "create_time": 1760003000.0,
        "update_time": 1760003100.0,
        "current_node": "s2",
        "mapping": {
            "s1": _make_node("s1", "s2", ["s2"], role="user", parts=["First standalone message."]),
            "s2": _make_node("s2", "s1", [], role="assistant", parts=["Cycle-safe reply."]),
        },
    }

    return [branching_project_conv, custom_gpt_conv, codex_export_conv, cyclic_standalone_conv]


@pytest.fixture()
def synthetic_chatgpt_dir(tmp_path: Path, synthetic_chatgpt_conversations: list[dict[str, Any]]) -> Path:
    """Write sharded conversations-000.json and conversations-001.json into a temp dir."""
    export_dir = tmp_path / "chatgpt_export_dir"
    export_dir.mkdir()
    (export_dir / "conversations-000.json").write_text(
        json.dumps(synthetic_chatgpt_conversations[:2], indent=2),
        encoding="utf-8",
    )
    (export_dir / "conversations-001.json").write_text(
        json.dumps(synthetic_chatgpt_conversations[2:], indent=2),
        encoding="utf-8",
    )
    return export_dir


@pytest.fixture()
def synthetic_chatgpt_zip(tmp_path: Path, synthetic_chatgpt_conversations: list[dict[str, Any]]) -> Path:
    """Write a synthetic ChatGPT .zip archive with sharded JSON files."""
    zip_path = tmp_path / "synthetic_chatgpt_export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("conversations-000.json", json.dumps(synthetic_chatgpt_conversations[:2]))
        zf.writestr("conversations-001.json", json.dumps(synthetic_chatgpt_conversations[2:]))
    return zip_path


@pytest.fixture()
def synthetic_codex_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Create synthetic active and archived Codex rollout JSONL trees with malformed lines."""
    sessions_dir = tmp_path / "codex_home" / "sessions" / "2026" / "11"
    archived_dir = tmp_path / "codex_home" / "archived_sessions"
    sessions_dir.mkdir(parents=True)
    archived_dir.mkdir(parents=True)

    # 1. Active session for team-a/service with duplicate event_msg, boilerplate, and 2 malformed lines
    rollout_1 = sessions_dir / "rollout-2026-11-20-alpha.jsonl"
    lines_1 = [
        json.dumps(
            {
                "type": "session_meta",
                "timestamp": "2026-11-20T10:00:00Z",
                "payload": {
                    "id": "sess-alpha-01",
                    "cwd": "/tmp/workspaces/team-a/service",
                    "timestamp": "2026-11-20T10:00:00Z",
                    "git": {"branch": "feat/auth"},
                },
            }
        ),
        '{"type": "response_item", "truncated_json": ',  # malformed line 1
        json.dumps(
            {
                "type": "response_item",
                "timestamp": "2026-11-20T10:01:00Z",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<environment_context>OS: mac</environment_context>\nImplement token refresh endpoint.",
                        }
                    ],
                },
            }
        ),
        json.dumps(
            {
                "type": "event_msg",
                "timestamp": "2026-11-20T10:01:00Z",
                "payload": {
                    "type": "user_message",
                    "message": "Implement token refresh endpoint.",
                },
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "timestamp": "2026-11-20T10:02:00Z",
                "payload": {
                    "type": "function_call",
                    "name": "run_tests",
                    "arguments": "{\"cmd\": \"pytest\"}",
                },
            }
        ),
        "not-even-json",  # malformed line 2
        json.dumps(
            {
                "type": "response_item",
                "timestamp": "2026-11-20T10:03:00Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Added /v1/token/refresh and verified unit tests pass.",
                        }
                    ],
                },
            }
        ),
    ]
    rollout_1.write_text("\n".join(lines_1) + "\n", encoding="utf-8")

    # 2. Archived session for colliding basename team-b/service + 1 malformed line
    rollout_2 = archived_dir / "rollout-2026-11-18-beta.jsonl"
    lines_2 = [
        json.dumps(
            {
                "type": "session_meta",
                "timestamp": "2026-11-18T09:00:00Z",
                "payload": {
                    "id": "sess-beta-02",
                    "cwd": "/tmp/workspaces/team-b/service",
                    "timestamp": "2026-11-18T09:00:00Z",
                },
            }
        ),
        json.dumps(
            {
                "type": "event_msg",
                "timestamp": "2026-11-18T09:05:00Z",
                "payload": {"type": "user_message", "message": "Switch worker queue port to 6380."},
            }
        ),
        "[1, 2, 3]",  # non-dict JSON line -> malformed line 3
        json.dumps(
            {
                "type": "event_msg",
                "timestamp": "2026-11-18T09:06:00Z",
                "payload": {"type": "agent_message", "message": "Updated Redis port config to 6380."},
            }
        ),
    ]
    rollout_2.write_text("\n".join(lines_2) + "\n", encoding="utf-8")

    # 3. Archived session without cwd -> unknown-project
    rollout_3 = archived_dir / "rollout-2026-11-15-nocwd.jsonl"
    lines_3 = [
        json.dumps(
            {
                "type": "event_msg",
                "timestamp": "2026-11-15T08:00:00Z",
                "payload": {"type": "user_message", "message": "Quick scratchpad check."},
            }
        ),
    ]
    rollout_3.write_text("\n".join(lines_3) + "\n", encoding="utf-8")

    return tmp_path / "codex_home" / "sessions", archived_dir
