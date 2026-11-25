"""Unit tests for Obsidian vault scaffolding, cross-agent rules, and sync."""

from __future__ import annotations

from pathlib import Path

from memory_bridge.vault.scaffold import init_vault
from memory_bridge.vault.sync import sync_to_vault


def test_vault_init_scaffolds_structure_and_agent_rules(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    repo = tmp_path / "repo"
    repo.mkdir()

    res1 = init_vault(vault_dir=vault, project="My Cool App", rules_dir=repo)
    assert (vault / "00_Index" / "README.md").is_file()
    assert (vault / "00_Index" / "PROJECTS.md").is_file()
    assert (vault / "00_Index" / "HANDOFF_TEMPLATE.md").is_file()
    assert (vault / "01_Projects" / "my-cool-app" / "project_prior_context.md").is_file()
    assert (vault / "02_Cross_Model_Handoffs").is_dir()
    assert (vault / "Archive").is_dir()

    agents_md = (repo / "AGENTS.md").read_text(encoding="utf-8")
    claude_md = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    plan_md = (repo / ".plans" / "template.md").read_text(encoding="utf-8")

    assert "01_Projects/my-cool-app/project_prior_context.md" in agents_md
    assert "02_Cross_Model_Handoffs/" in agents_md
    assert "Archive/" in agents_md
    assert claude_md.startswith("@AGENTS.md")
    assert "Vault Handoff Checklist" in plan_md

    # Idempotent re-run skips existing files
    res2 = init_vault(vault_dir=vault, project="My Cool App", rules_dir=repo)
    assert len(res2.created) == 0
    assert len(res2.skipped) == len(res1.created)


def test_sync_vault_archives_superseded_context_and_writes_handoff(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    init_vault(vault_dir=vault)

    # First version of project_prior_context.md
    src_file = tmp_path / "project_prior_context.md"
    src_file.write_text("# Demo\n\n## Finalised Decisions & Architecture\n- v1\n", encoding="utf-8")
    res1 = sync_to_vault(vault_dir=vault, source_path=src_file, project="Demo App")
    assert res1.synced_projects == ["demo-app"]
    assert len(res1.archived_files) == 0

    # Updated version -> old copy must be moved/copied to Archive/
    src_file.write_text("# Demo\n\n## Finalised Decisions & Architecture\n- v2\n", encoding="utf-8")
    res2 = sync_to_vault(
        vault_dir=vault,
        source_path=src_file,
        project="Demo App",
        write_handoff=True,
        agent="claude",
    )
    assert len(res2.archived_files) == 1
    assert res2.archived_files[0].parent == vault / "Archive"
    assert "- v1" in res2.archived_files[0].read_text(encoding="utf-8")
    assert "- v2" in (vault / "01_Projects" / "demo-app" / "project_prior_context.md").read_text(
        encoding="utf-8"
    )
    assert len(res2.handoffs_written) == 1
    assert res2.handoffs_written[0].name.endswith("_demo-app_claude.md")

    index_md = (vault / "00_Index" / "PROJECTS.md").read_text(encoding="utf-8")
    assert "[[01_Projects/demo-app/project_prior_context]]" in index_md


def test_sync_vault_multi_project_export_with_distill(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    export_root = tmp_path / "codex_export"
    proj_a = export_root / "Service Alpha"
    proj_b = export_root / "Service Beta"
    proj_a.mkdir(parents=True)
    proj_b.mkdir(parents=True)

    (proj_a / "CODEX_PROJECT_MEMORY.md").write_text(
        "- Decided to use uvicorn workers with 4 processes.", encoding="utf-8"
    )
    (proj_b / "CODEX_PROJECT_MEMORY.md").write_text(
        "- Constraint: database migrations must remain backwards compatible.", encoding="utf-8"
    )

    res = sync_to_vault(vault_dir=vault, source_path=export_root, distill=True)
    assert sorted(res.synced_projects) == ["service-alpha", "service-beta"]
    assert (vault / "01_Projects" / "service-alpha" / "project_prior_context.md").is_file()
    assert (vault / "01_Projects" / "service-beta" / "project_prior_context.md").is_file()
