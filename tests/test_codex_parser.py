"""Unit tests for the Codex rollout JSONL converter."""

from __future__ import annotations

from pathlib import Path

from memory_bridge.parsers.codex import convert_codex_sessions


def test_convert_codex_sessions_skips_malformed_and_groups_by_cwd(
    tmp_path: Path,
    synthetic_codex_tree: tuple[Path, Path],
) -> None:
    sessions_dir, archived_dir = synthetic_codex_tree
    out_dir = tmp_path / "codex_out"

    summary = convert_codex_sessions(
        output_dir=out_dir,
        sessions_dir=sessions_dir,
        archived_dir=archived_dir,
        include_raw=True,
    )

    assert summary.sessions_scanned == 3
    assert summary.sessions_exported == 3
    assert summary.active_sessions == 1
    assert summary.archived_sessions == 2
    assert summary.malformed_lines_skipped == 3
    assert summary.projects_written == 3

    index_text = (out_dir / "INDEX.md").read_text(encoding="utf-8")
    assert "Malformed/Truncated JSONL Lines Skipped:** 3" in index_text

    # Colliding folder basenames (/team-a/service vs /team-b/service) are disambiguated
    team_a_mem = (out_dir / "team-a-service" / "CODEX_PROJECT_MEMORY.md").read_text(encoding="utf-8")
    assert "Implement token refresh endpoint." in team_a_mem
    # Deduplicated event_msg and stripped <environment_context>
    assert team_a_mem.count("Implement token refresh endpoint.") == 1
    assert "<environment_context>" not in team_a_mem
    assert (out_dir / "team-a-service" / "raw" / "sess-alpha-01.md").is_file()

    team_b_mem = (out_dir / "team-b-service" / "CODEX_PROJECT_MEMORY.md").read_text(encoding="utf-8")
    assert "Updated Redis port config to 6380." in team_b_mem

    unknown_mem = (out_dir / "unknown-project" / "CODEX_PROJECT_MEMORY.md").read_text(encoding="utf-8")
    assert "Quick scratchpad check." in unknown_mem


def test_convert_codex_sessions_handles_missing_dirs(tmp_path: Path) -> None:
    out_dir = tmp_path / "empty_codex"
    summary = convert_codex_sessions(
        output_dir=out_dir,
        sessions_dir=tmp_path / "does-not-exist",
        archived_dir=tmp_path / "also-missing",
    )
    assert summary.sessions_scanned == 0
    assert summary.sessions_exported == 0
    assert (out_dir / "INDEX.md").is_file()


def test_convert_codex_sessions_include_tool_calls(
    tmp_path: Path,
    synthetic_codex_tree: tuple[Path, Path],
) -> None:
    sessions_dir, archived_dir = synthetic_codex_tree
    out_dir = tmp_path / "codex_tools"
    convert_codex_sessions(
        output_dir=out_dir,
        sessions_dir=sessions_dir,
        archived_dir=archived_dir,
        include_tool_calls=True,
    )
    team_a_mem = (out_dir / "team-a-service" / "CODEX_PROJECT_MEMORY.md").read_text(encoding="utf-8")
    assert "[tool call `run_tests`]" in team_a_mem
