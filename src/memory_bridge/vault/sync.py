"""Synchronize distilled memory and project artifacts into an Obsidian vault."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from memory_bridge.distill.providers import LLMProvider
from memory_bridge.distill.synthesizer import distill_memory
from memory_bridge.utils import ensure_unique_archive_path, slugify, today_iso, utc_now_iso
from memory_bridge.vault.scaffold import init_vault

_MEMORY_FILENAMES = (
    "project_prior_context.md",
    "PROJECT_MEMORY.md",
    "CODEX_PROJECT_MEMORY.md",
)


@dataclass(slots=True)
class SyncResult:
    """Summary of a vault synchronization run."""

    vault_dir: Path
    synced_projects: list[str] = field(default_factory=list)
    archived_files: list[Path] = field(default_factory=list)
    handoffs_written: list[Path] = field(default_factory=list)
    index_path: Path | None = None


def rebuild_projects_index(vault_dir: Path) -> Path:
    """Scan 01_Projects/*/ and rewrite 00_Index/PROJECTS.md."""
    vault_root = Path(vault_dir).expanduser().resolve()
    projects_dir = vault_root / "01_Projects"
    index_path = vault_root / "00_Index" / "PROJECTS.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[str] = []
    if projects_dir.exists():
        for entry in sorted(projects_dir.iterdir(), key=lambda p: p.name):
            if not entry.is_dir():
                continue
            slug = entry.name
            ctx_path = entry / "project_prior_context.md"
            ctx_link = (
                f"[[01_Projects/{slug}/project_prior_context]]"
                if ctx_path.exists()
                else "_missing_"
            )
            sources = [
                name
                for name in ("PROJECT_MEMORY.md", "CODEX_PROJECT_MEMORY.md")
                if (entry / name).exists()
            ]
            sources_str = ", ".join(f"`{s}`" for s in sources) if sources else "-"
            target_mtime = ctx_path if ctx_path.exists() else entry
            mtime_str = datetime.fromtimestamp(
                target_mtime.stat().st_mtime, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC")
            rows.append(f"| `{slug}` | {ctx_link} | {sources_str} | {mtime_str} |")

    lines = [
        "---",
        f"updated_at: {utc_now_iso()}",
        f"projects: {len(rows)}",
        "---",
        "",
        "# Projects Index",
        "",
        "| Project Slug | Context Note | Memory Sources | Last Updated |",
        "| :--- | :--- | :--- | :--- |",
        *rows,
        "",
    ]
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path


def _discover_sync_targets(source_path: Path, explicit_project: str | None) -> list[tuple[str, Path]]:
    resolved = source_path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Sync source path does not exist: {resolved}")

    if resolved.is_file():
        inferred = explicit_project or (
            resolved.parent.name if resolved.parent.name not in {"", "."} else resolved.stem
        )
        return [(slugify(inferred, fallback="project"), resolved)]

    direct_memory = any((resolved / name).is_file() for name in _MEMORY_FILENAMES)
    if direct_memory or explicit_project:
        slug = slugify(explicit_project or resolved.name, fallback="project")
        return [(slug, resolved)]

    targets: list[tuple[str, Path]] = []
    seen_dirs: set[Path] = set()

    def _add_if_project_dir(candidate: Path, forced_slug: str | None = None) -> None:
        if not candidate.is_dir() or candidate in seen_dirs:
            return
        if any((candidate / name).is_file() for name in _MEMORY_FILENAMES):
            seen_dirs.add(candidate)
            slug = slugify(forced_slug or candidate.name, fallback="project")
            targets.append((slug, candidate))

    # ChatGPT export layout (projects/*, gpts/*, codex, standalone)
    for bucket in ("projects", "gpts"):
        bucket_dir = resolved / bucket
        if bucket_dir.is_dir():
            for child in sorted(bucket_dir.iterdir()):
                _add_if_project_dir(child)
    for single_bucket in ("codex", "standalone"):
        _add_if_project_dir(resolved / single_bucket, forced_slug=f"chatgpt-{single_bucket}")

    # Direct child project directories (e.g., Codex export root or distilled folders)
    for child in sorted(resolved.iterdir()):
        if child.name in {"projects", "gpts", "codex", "standalone", "raw"}:
            continue
        _add_if_project_dir(child)

    if not targets:
        raise ValueError(
            f"No project memory files ({', '.join(_MEMORY_FILENAMES)}) found under: {resolved}"
        )
    return targets


def _archive_if_changed(
    target_path: Path,
    new_content: str,
    archive_dir: Path,
    project_slug: str,
    archive_previous: bool,
) -> Path | None:
    if not archive_previous or not target_path.exists():
        return None
    old_content = target_path.read_text(encoding="utf-8", errors="replace")
    if old_content == new_content:
        return None
    archive_name = f"{today_iso()}_{project_slug}_{target_path.name}"
    archived_path = ensure_unique_archive_path(archive_dir, archive_name)
    archived_path.write_text(old_content, encoding="utf-8")
    return archived_path


def _write_sync_handoff(
    handoffs_dir: Path,
    project_slug: str,
    agent_slug: str,
    synced_files: list[str],
    archived_path: Path | None,
) -> Path:
    filename = f"{today_iso()}_{project_slug}_{agent_slug}.md"
    target = ensure_unique_archive_path(handoffs_dir, filename)
    lines = [
        "---",
        f"date: {today_iso()}",
        f"project: {project_slug}",
        f"agent: {agent_slug}",
        "status: synced",
        "---",
        "",
        f"# Handoff: {project_slug} ({agent_slug})",
        "",
        "## Summary of Sync",
        *[f"- Updated `01_Projects/{project_slug}/{fname}`" for fname in synced_files],
    ]
    if archived_path is not None:
        lines.append(f"- Archived previous context to `Archive/{archived_path.name}`")
    lines.extend(
        [
            "",
            "## Next Steps",
            f"- Review `[[01_Projects/{project_slug}/project_prior_context]]` before starting implementation.",
            "",
        ]
    )
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def sync_to_vault(
    vault_dir: Path,
    source_path: Path,
    project: str | None = None,
    distill: bool = False,
    provider: str = "extractive",
    model: str | None = None,
    archive_previous: bool = True,
    write_handoff: bool = False,
    agent: str = "memory-bridge",
    redact: bool = True,
    provider_instance: LLMProvider | None = None,
) -> SyncResult:
    """Sync project memory files into an Obsidian vault with archival safety."""
    vault_root = Path(vault_dir).expanduser().resolve()
    init_vault(vault_root)

    archive_dir = vault_root / "Archive"
    projects_dir = vault_root / "01_Projects"
    handoffs_dir = vault_root / "02_Cross_Model_Handoffs"

    targets = _discover_sync_targets(Path(source_path), explicit_project=project)
    result = SyncResult(vault_dir=vault_root)
    agent_slug = slugify(agent, fallback="memory-bridge")

    for project_slug, target_src in targets:
        dest_project_dir = projects_dir / project_slug
        dest_project_dir.mkdir(parents=True, exist_ok=True)
        synced_filenames: list[str] = []
        archived_ctx: Path | None = None

        if target_src.is_file():
            if target_src.name == "project_prior_context.md" and not distill:
                new_content = target_src.read_text(encoding="utf-8", errors="replace")
                dest_ctx = dest_project_dir / "project_prior_context.md"
                archived_ctx = _archive_if_changed(
                    dest_ctx, new_content, archive_dir, project_slug, archive_previous
                )
                if archived_ctx:
                    result.archived_files.append(archived_ctx)
                dest_ctx.write_text(new_content, encoding="utf-8")
                synced_filenames.append("project_prior_context.md")
            else:
                dest_copy = dest_project_dir / target_src.name
                shutil.copy2(target_src, dest_copy)
                synced_filenames.append(target_src.name)
                if distill:
                    distill_res = distill_memory(
                        inputs=[target_src],
                        project_name=project or project_slug,
                        provider=provider,
                        model=model,
                        redact=redact,
                        provider_instance=provider_instance,
                    )
                    dest_ctx = dest_project_dir / "project_prior_context.md"
                    archived_ctx = _archive_if_changed(
                        dest_ctx, distill_res.content, archive_dir, project_slug, archive_previous
                    )
                    if archived_ctx:
                        result.archived_files.append(archived_ctx)
                    dest_ctx.write_text(distill_res.content, encoding="utf-8")
                    synced_filenames.append("project_prior_context.md")
        else:
            memory_inputs: list[Path] = []
            for mem_name in ("PROJECT_MEMORY.md", "CODEX_PROJECT_MEMORY.md"):
                src_mem = target_src / mem_name
                if src_mem.is_file():
                    shutil.copy2(src_mem, dest_project_dir / mem_name)
                    synced_filenames.append(mem_name)
                    memory_inputs.append(src_mem)

            src_ctx = target_src / "project_prior_context.md"
            if distill and (memory_inputs or src_ctx.is_file()):
                distill_inputs = memory_inputs if memory_inputs else [src_ctx]
                distill_res = distill_memory(
                    inputs=distill_inputs,
                    project_name=project or project_slug,
                    provider=provider,
                    model=model,
                    redact=redact,
                    provider_instance=provider_instance,
                )
                dest_ctx = dest_project_dir / "project_prior_context.md"
                archived_ctx = _archive_if_changed(
                    dest_ctx, distill_res.content, archive_dir, project_slug, archive_previous
                )
                if archived_ctx:
                    result.archived_files.append(archived_ctx)
                dest_ctx.write_text(distill_res.content, encoding="utf-8")
                synced_filenames.append("project_prior_context.md")
            elif src_ctx.is_file():
                new_content = src_ctx.read_text(encoding="utf-8", errors="replace")
                dest_ctx = dest_project_dir / "project_prior_context.md"
                archived_ctx = _archive_if_changed(
                    dest_ctx, new_content, archive_dir, project_slug, archive_previous
                )
                if archived_ctx:
                    result.archived_files.append(archived_ctx)
                dest_ctx.write_text(new_content, encoding="utf-8")
                synced_filenames.append("project_prior_context.md")

        if project_slug not in result.synced_projects:
            result.synced_projects.append(project_slug)

        if write_handoff and synced_filenames:
            handoff_path = _write_sync_handoff(
                handoffs_dir=handoffs_dir,
                project_slug=project_slug,
                agent_slug=agent_slug,
                synced_files=synced_filenames,
                archived_path=archived_ctx,
            )
            result.handoffs_written.append(handoff_path)

    result.index_path = rebuild_projects_index(vault_root)
    return result
