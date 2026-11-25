"""Unit tests for the ChatGPT export parser."""

from __future__ import annotations

import json
from pathlib import Path

from memory_bridge.parsers.chatgpt import export_chatgpt


def test_export_chatgpt_prunes_abandoned_branches_and_groups(
    tmp_path: Path,
    synthetic_chatgpt_dir: Path,
) -> None:
    out_dir = tmp_path / "out_dir"
    names_map = tmp_path / "names.json"
    names_map.write_text(json.dumps({"g-writer999": "Release Assistant"}), encoding="utf-8")

    summary = export_chatgpt(
        input_path=synthetic_chatgpt_dir,
        output_dir=out_dir,
        names_map_path=names_map,
    )

    assert summary.total_conversations == 4
    assert summary.exported_conversations == 4
    assert (out_dir / "INDEX.md").is_file()
    assert (out_dir / "manifest.json").is_file()

    project_mem = (out_dir / "projects" / "alpha-platform" / "PROJECT_MEMORY.md").read_text(
        encoding="utf-8"
    )
    assert "PostgreSQL 16 with Alembic migrations" in project_mem
    assert "ACTIVE_LEAF_CONFIRMED" in project_mem
    assert "[attachment: image_asset_pointer]" in project_mem
    # Abandoned sibling branch, hidden system prompt, tool payload, and citation tokens must be excluded
    assert "ABANDONED_BRANCH" not in project_mem
    assert "Internal system prompt" not in project_mem
    assert "TOOL_PAYLOAD" not in project_mem
    assert "\ue200" not in project_mem

    # Raw transcripts are opt-in only
    assert not (out_dir / "projects" / "alpha-platform" / "raw").exists()

    # Custom GPT mapped via names.json, Codex export, and standalone group
    assert (out_dir / "gpts" / "release-assistant" / "PROJECT_MEMORY.md").is_file()
    assert (out_dir / "codex" / "PROJECT_MEMORY.md").is_file()
    standalone_mem = (out_dir / "standalone" / "PROJECT_MEMORY.md").read_text(encoding="utf-8")
    assert "Cycle-safe reply." in standalone_mem


def test_export_chatgpt_zip_include_raw_and_group_filter(
    tmp_path: Path,
    synthetic_chatgpt_zip: Path,
) -> None:
    out_dir = tmp_path / "out_zip"
    summary = export_chatgpt(
        input_path=synthetic_chatgpt_zip,
        output_dir=out_dir,
        include_raw=True,
        include_tools=True,
        max_chars_per_turn=40,
        group_filter="projects",
    )

    assert summary.exported_conversations == 1
    proj_dir = out_dir / "projects" / "alpha-platform"
    compact_text = (proj_dir / "PROJECT_MEMORY.md").read_text(encoding="utf-8")
    assert "[truncated" in compact_text

    raw_files = list((proj_dir / "raw").glob("*.md"))
    assert len(raw_files) == 1
    raw_text = raw_files[0].read_text(encoding="utf-8")
    assert "ACTIVE_LEAF_CONFIRMED: Connection pool max_size is 20." in raw_text
    assert not (out_dir / "standalone").exists()
