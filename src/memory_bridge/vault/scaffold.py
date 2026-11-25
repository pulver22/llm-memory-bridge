"""Obsidian vault and cross-agent rule file scaffolding (AGENTS.md, CLAUDE.md, .plans/template.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from memory_bridge.distill.extractive import REQUIRED_SECTIONS, render_context_document
from memory_bridge.utils import ensure_unique_archive_path, slugify, today_iso, utc_now_iso


@dataclass(slots=True)
class VaultInitResult:
    """Summary of vault and rule files created, skipped, or archived."""

    vault_dir: Path
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    archived: list[Path] = field(default_factory=list)


def render_agents_md(vault_path_hint: str, project_slug: str = "<project-slug>") -> str:
    """Render shared cross-agent instructions for Claude, Codex, and Antigravity (agy)."""
    return f"""# Cross-Agent Memory & Handoff Protocol

This repository coordinates work across **Claude Code**, **Codex**, and **Antigravity (`agy`)** using a shared, LLM-agnostic Obsidian vault (`{vault_path_hint}`).

## 1. Before Starting Any Task
1. Read `00_Index/PROJECTS.md` in the vault to confirm the project slug (`{project_slug}`).
2. Read `01_Projects/{project_slug}/project_prior_context.md`.
3. Read the most recent 2–3 handoff notes in `02_Cross_Model_Handoffs/` matching `{project_slug}`.
4. For multi-step work, create or update a task plan from `.plans/template.md`.

## 2. During & After Work (Handoff Discipline)
1. **Write a dated handoff note** to:
   `02_Cross_Model_Handoffs/YYYY-MM-DD_{project_slug}_<agent>.md`
   (where `<agent>` is `claude`, `codex`, `agy`, etc.).
2. **Update `01_Projects/{project_slug}/project_prior_context.md`** whenever durable architecture decisions, constraints, active state, or next steps change.
3. Keep `project_prior_context.md` limited to the four canonical sections:
   - `Finalised Decisions & Architecture`
   - `Active Work & Current State`
   - `Key Facts, Constraints & Parameters`
   - `Open Questions & Next Steps`

## 3. Archival & Safety Rules (Mandatory)
- **Archive, never delete:** Move superseded notes or old snapshots to `Archive/` instead of deleting them.
- **No secrets or credentials:** NEVER write API keys, tokens, passwords, `.env` contents, or private keys into vault notes, handoffs, or `.plans/`.
- **Use kebab-case project slugs:** Always store project directories under `01_Projects/<kebab-case-slug>/`.
"""


def render_claude_md() -> str:
    """Render CLAUDE.md delegating shared rules via @AGENTS.md."""
    return """@AGENTS.md

## Claude Code Notes
- Always load `01_Projects/<slug>/project_prior_context.md` and recent `02_Cross_Model_Handoffs/` notes before proposing architectural changes.
- Record completed work in `02_Cross_Model_Handoffs/YYYY-MM-DD_<project>_claude.md`.
"""


def render_plan_template(project_slug: str = "<project-slug>") -> str:
    """Render .plans/template.md for structured cross-agent execution plans."""
    return f"""# Task Plan: <Short Descriptive Title>

- **Project Slug:** `{project_slug}`
- **Agent:** `<claude | codex | agy>`
- **Date:** `YYYY-MM-DD`
- **Status:** `draft | in-progress | blocked | done`

## 1. Context Loaded from Vault
- [ ] Read `01_Projects/{project_slug}/project_prior_context.md`
- [ ] Checked recent `02_Cross_Model_Handoffs/` notes for `{project_slug}`

## 2. Goal & Scope
- **Goal:** ...
- **In Scope:** ...
- **Out of Scope:** ...

## 3. Implementation Steps
1. ...
2. ...
3. ...

## 4. Verification Checklist
- [ ] Relevant automated tests pass (`pytest` / test suite)
- [ ] No secrets, tokens, or raw personal exports staged

## 5. Vault Handoff Checklist
- [ ] Wrote `02_Cross_Model_Handoffs/YYYY-MM-DD_{project_slug}_<agent>.md`
- [ ] Updated `01_Projects/{project_slug}/project_prior_context.md` (if durable state/decisions changed)
- [ ] Moved any superseded notes to `Archive/` instead of deleting
"""


def _render_vault_readme() -> str:
    return f"""---
updated_at: {utc_now_iso()}
---

# LLM Memory Bridge — Central Obsidian Vault

This vault stores model-agnostic project memory shared across ChatGPT, Codex, Claude Code, and Antigravity (`agy`).

## Directory Structure

- `00_Index/` — Vault guide (`README.md`), project directory (`PROJECTS.md`), handoff template, and agent rule templates.
- `01_Projects/<slug>/` — Per-project `project_prior_context.md` and distilled memory notes (`PROJECT_MEMORY.md`, `CODEX_PROJECT_MEMORY.md`).
- `02_Cross_Model_Handoffs/` — Dated task handoff logs named `YYYY-MM-DD_<project>_<agent>.md`.
- `Archive/` — Superseded `project_prior_context.md` snapshots and retired notes (never delete history).

## Safety Rules

1. Never store API keys, tokens, `.env` values, or passwords in this vault.
2. Move superseded context files to `Archive/` rather than deleting them.
"""


def _render_handoff_template() -> str:
    return """---
date: YYYY-MM-DD
project: <project-slug>
agent: <claude|codex|agy>
status: completed
---

# Handoff: <project-slug> (<agent>)

## Summary of Changes
- ...

## Decisions & Constraints Updated
- ...

## Verification Performed
- ...

## Next Steps
- ...
"""


def _render_initial_projects_index() -> str:
    return f"""---
updated_at: {utc_now_iso()}
---

# Projects Index

| Project Slug | Context Note | Memory Sources | Last Updated |
| :--- | :--- | :--- | :--- |
"""


def _write_managed_file(
    path: Path,
    content: str,
    force: bool,
    archive_dir: Path | None,
    result: VaultInitResult,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not force:
            result.skipped.append(path)
            return
        if archive_dir is not None and path.read_text(encoding="utf-8", errors="replace") != content:
            archived_name = f"{today_iso()}_{path.name}"
            archived_target = ensure_unique_archive_path(archive_dir, archived_name)
            archived_target.write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            result.archived.append(archived_target)
    path.write_text(content, encoding="utf-8")
    result.created.append(path)


def init_vault(
    vault_dir: Path,
    project: str | None = None,
    rules_dir: Path | None = None,
    force: bool = False,
) -> VaultInitResult:
    """Initialize an LLM-agnostic Obsidian vault and optional repo cross-agent rule files."""
    vault_root = Path(vault_dir).expanduser().resolve()
    index_dir = vault_root / "00_Index"
    templates_dir = index_dir / "templates"
    projects_dir = vault_root / "01_Projects"
    handoffs_dir = vault_root / "02_Cross_Model_Handoffs"
    archive_dir = vault_root / "Archive"

    for directory in (index_dir, templates_dir, projects_dir, handoffs_dir, archive_dir):
        directory.mkdir(parents=True, exist_ok=True)

    result = VaultInitResult(vault_dir=vault_root)
    project_slug = slugify(project, fallback="<project-slug>") if project else "<project-slug>"

    _write_managed_file(index_dir / "README.md", _render_vault_readme(), force, archive_dir, result)
    _write_managed_file(
        index_dir / "PROJECTS.md",
        _render_initial_projects_index(),
        force=False if (index_dir / "PROJECTS.md").exists() and not force else force,
        archive_dir=archive_dir,
        result=result,
    )
    _write_managed_file(
        index_dir / "HANDOFF_TEMPLATE.md",
        _render_handoff_template(),
        force,
        archive_dir,
        result,
    )
    _write_managed_file(
        templates_dir / "AGENTS.md",
        render_agents_md(str(vault_root), project_slug),
        force,
        archive_dir,
        result,
    )
    _write_managed_file(
        templates_dir / "CLAUDE.md",
        render_claude_md(),
        force,
        archive_dir,
        result,
    )
    _write_managed_file(
        templates_dir / "plan_template.md",
        render_plan_template(project_slug),
        force,
        archive_dir,
        result,
    )

    if project:
        starter_slug = slugify(project, fallback="project")
        starter_path = projects_dir / starter_slug / "project_prior_context.md"
        starter_content = render_context_document(
            project_name=project.strip(),
            project_slug=starter_slug,
            sections={sec: [] for sec in REQUIRED_SECTIONS},
            source_files=[],
            distillation_mode="manual",
        )
        _write_managed_file(starter_path, starter_content, force, archive_dir, result)

    if rules_dir is not None:
        rules_root = Path(rules_dir).expanduser().resolve()
        rules_root.mkdir(parents=True, exist_ok=True)
        _write_managed_file(
            rules_root / "AGENTS.md",
            render_agents_md(str(vault_root), project_slug),
            force,
            archive_dir=None,
            result=result,
        )
        _write_managed_file(
            rules_root / "CLAUDE.md",
            render_claude_md(),
            force,
            archive_dir=None,
            result=result,
        )
        _write_managed_file(
            rules_root / ".plans" / "template.md",
            render_plan_template(project_slug),
            force,
            archive_dir=None,
            result=result,
        )

    return result
