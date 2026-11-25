"""End-to-end CLI smoke tests using synthetic data."""

from __future__ import annotations

from pathlib import Path

import pytest

from memory_bridge import __version__
from memory_bridge.cli import main


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_cli_end_to_end_pipeline(
    tmp_path: Path,
    synthetic_chatgpt_zip: Path,
    synthetic_codex_tree: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    sessions_dir, archived_dir = synthetic_codex_tree
    cg_out = tmp_path / "cg_out"
    cx_out = tmp_path / "cx_out"
    distilled_out = tmp_path / "project_prior_context.md"
    vault_dir = tmp_path / "obsidian_vault"
    repo_dir = tmp_path / "target_repo"
    repo_dir.mkdir()

    assert main(["export", "--input", str(synthetic_chatgpt_zip), "--output", str(cg_out)]) == 0
    assert (cg_out / "projects" / "alpha-platform" / "PROJECT_MEMORY.md").is_file()

    assert (
        main(
            [
                "codex",
                "--sessions-dir",
                str(sessions_dir),
                "--archived-dir",
                str(archived_dir),
                "--output",
                str(cx_out),
            ]
        )
        == 0
    )
    assert (cx_out / "team-a-service" / "CODEX_PROJECT_MEMORY.md").is_file()

    assert (
        main(
            [
                "distill",
                "--input",
                str(cg_out / "projects" / "alpha-platform" / "PROJECT_MEMORY.md"),
                str(cx_out / "team-a-service" / "CODEX_PROJECT_MEMORY.md"),
                "--project",
                "Alpha Platform",
                "--output",
                str(distilled_out),
            ]
        )
        == 0
    )
    assert distilled_out.is_file()

    assert (
        main(
            [
                "vault-init",
                "--vault",
                str(vault_dir),
                "--project",
                "alpha-platform",
                "--rules-dir",
                str(repo_dir),
            ]
        )
        == 0
    )
    assert (repo_dir / "AGENTS.md").is_file()
    assert (repo_dir / "CLAUDE.md").is_file()
    assert (repo_dir / ".plans" / "template.md").is_file()

    assert (
        main(
            [
                "sync-vault",
                "--vault",
                str(vault_dir),
                "--source",
                str(distilled_out),
                "--project",
                "alpha-platform",
                "--write-handoff",
                "--agent",
                "agy",
            ]
        )
        == 0
    )
    assert (vault_dir / "01_Projects" / "alpha-platform" / "project_prior_context.md").is_file()
    assert list((vault_dir / "02_Cross_Model_Handoffs").glob("*_alpha-platform_agy.md"))

    capsys.readouterr()
    # Verify non-zero exit code on missing input
    rc_err = main(["export", "--input", str(tmp_path / "missing.zip")])
    assert rc_err == 1
    assert "Error:" in capsys.readouterr().err
