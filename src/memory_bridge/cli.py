"""Unified CLI entrypoint for llm-memory-bridge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from memory_bridge import __version__
from memory_bridge.distill.providers import (
    SUPPORTED_PROVIDERS,
    ProviderConfigError,
    ProviderRequestError,
)
from memory_bridge.distill.synthesizer import distill_memory
from memory_bridge.parsers.chatgpt import export_chatgpt
from memory_bridge.parsers.codex import convert_codex_sessions
from memory_bridge.vault.scaffold import init_vault
from memory_bridge.vault.sync import sync_to_vault


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level ArgumentParser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="memory-bridge",
        description="Model-agnostic ChatGPT & Codex memory export, distillation, and Obsidian vault bridge.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. export
    p_export = subparsers.add_parser(
        "export",
        help="Parse a ChatGPT export (.zip, dir, or conversations*.json) into compact Markdown.",
    )
    p_export.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to ChatGPT export .zip, extracted directory, or conversations*.json file.",
    )
    p_export.add_argument(
        "--output",
        default=Path("chatgpt_memory_export"),
        type=Path,
        help="Output directory for grouped Markdown memory (default: ./chatgpt_memory_export).",
    )
    p_export.add_argument(
        "--include-raw",
        action="store_true",
        help="Also write full untruncated per-conversation Markdown files under raw/.",
    )
    p_export.add_argument(
        "--include-tools",
        action="store_true",
        help="Include tool messages in active conversation chains.",
    )
    p_export.add_argument(
        "--max-chars-per-turn",
        type=int,
        default=1200,
        help="Max characters per turn in PROJECT_MEMORY.md (0 disables truncation; default: 1200).",
    )
    p_export.add_argument(
        "--max-turns-per-chat",
        type=int,
        default=0,
        help="Optional cap on most recent turns per conversation (0 = all; default: 0).",
    )
    p_export.add_argument(
        "--names-map",
        type=Path,
        default=None,
        help="Optional JSON file mapping gizmo_id (g-p-..., g-...) to display names.",
    )
    p_export.add_argument(
        "--group",
        choices=("all", "projects", "gpts", "codex", "standalone"),
        default="all",
        help="Filter exported conversation groups (default: all).",
    )

    # 2. codex
    p_codex = subparsers.add_parser(
        "codex",
        help="Convert local Codex session rollouts (*.jsonl) into per-project Markdown.",
    )
    p_codex.add_argument(
        "--sessions-dir",
        type=Path,
        default=Path.home() / ".codex" / "sessions",
        help="Active Codex sessions root (default: ~/.codex/sessions).",
    )
    p_codex.add_argument(
        "--archived-dir",
        type=Path,
        default=Path.home() / ".codex" / "archived_sessions",
        help="Archived Codex sessions root (default: ~/.codex/archived_sessions).",
    )
    p_codex.add_argument(
        "--extra-dir",
        action="append",
        type=Path,
        default=[],
        help="Additional directory to scan recursively for rollout-*.jsonl files.",
    )
    p_codex.add_argument(
        "--output",
        default=Path("codex_sessions_markdown"),
        type=Path,
        help="Output directory for per-project Codex Markdown (default: ./codex_sessions_markdown).",
    )
    p_codex.add_argument(
        "--include-raw",
        action="store_true",
        help="Also write full per-session Markdown files under <project>/raw/.",
    )
    p_codex.add_argument(
        "--include-tool-calls",
        action="store_true",
        help="Include concise summaries of tool calls and outputs.",
    )
    p_codex.add_argument(
        "--max-chars-per-turn",
        type=int,
        default=1200,
        help="Max characters per turn in CODEX_PROJECT_MEMORY.md (default: 1200).",
    )

    # 3. distill
    p_distill = subparsers.add_parser(
        "distill",
        help="Distill verbose Markdown transcripts into a 4-section project_prior_context.md.",
    )
    p_distill.add_argument(
        "--input",
        nargs="+",
        required=True,
        type=Path,
        help="One or more Markdown files or directories to distill.",
    )
    p_distill.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output path for distilled project_prior_context.md.",
    )
    p_distill.add_argument(
        "--project",
        default=None,
        help="Human-readable project name (inferred from input path if omitted).",
    )
    p_distill.add_argument(
        "--provider",
        choices=SUPPORTED_PROVIDERS,
        default="extractive",
        help="Synthesis mode/provider (default: extractive).",
    )
    p_distill.add_argument(
        "--model",
        default=None,
        help="Optional model override for the selected LLM provider.",
    )
    p_distill.add_argument(
        "--max-chars",
        type=int,
        default=12000,
        help="Target maximum character length for output (default: 12000).",
    )
    p_distill.add_argument(
        "--chunk-chars",
        type=int,
        default=48000,
        help="Chunk size for LLM map-reduce synthesis (default: 48000).",
    )
    p_distill.add_argument(
        "--no-redact",
        action="store_true",
        help="Disable automatic secret/token redaction before synthesis.",
    )

    # 4. vault-init
    p_init = subparsers.add_parser(
        "vault-init",
        help="Initialize an Obsidian vault structure and optional cross-agent rule files.",
    )
    p_init.add_argument(
        "--vault",
        required=True,
        type=Path,
        help="Target Obsidian vault directory.",
    )
    p_init.add_argument(
        "--project",
        default=None,
        help="Optional project name/slug to scaffold under 01_Projects/<slug>/.",
    )
    p_init.add_argument(
        "--rules-dir",
        type=Path,
        default=None,
        help="Optional repo directory in which to generate AGENTS.md, CLAUDE.md, and .plans/template.md.",
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files (archiving overwritten vault notes to Archive/).",
    )

    # 5. sync-vault
    p_sync = subparsers.add_parser(
        "sync-vault",
        help="Sync project memory files or export directories into the Obsidian vault.",
    )
    p_sync.add_argument(
        "--vault",
        required=True,
        type=Path,
        help="Target Obsidian vault directory.",
    )
    p_sync.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Source file, single project directory, or multi-project export root.",
    )
    p_sync.add_argument(
        "--project",
        default=None,
        help="Project name/slug override (recommended when syncing a single file).",
    )
    p_sync.add_argument(
        "--distill",
        action="store_true",
        help="Run distillation to generate/update project_prior_context.md during sync.",
    )
    p_sync.add_argument(
        "--provider",
        choices=SUPPORTED_PROVIDERS,
        default="extractive",
        help="Distillation provider when --distill is set (default: extractive).",
    )
    p_sync.add_argument(
        "--model",
        default=None,
        help="Optional model override when --distill uses an LLM provider.",
    )
    p_sync.add_argument(
        "--no-archive",
        action="store_true",
        help="Do not copy superseded project_prior_context.md files into Archive/.",
    )
    p_sync.add_argument(
        "--write-handoff",
        action="store_true",
        help="Write a dated handoff note under 02_Cross_Model_Handoffs/.",
    )
    p_sync.add_argument(
        "--agent",
        default="memory-bridge",
        help="Agent identifier used in handoff filenames (default: memory-bridge).",
    )
    p_sync.add_argument(
        "--no-redact",
        action="store_true",
        help="Disable automatic secret redaction when --distill is enabled.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the memory-bridge CLI and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.command == "export":
            summary = export_chatgpt(
                input_path=args.input,
                output_dir=args.output,
                include_raw=args.include_raw,
                include_tools=args.include_tools,
                max_chars_per_turn=args.max_chars_per_turn,
                max_turns_per_chat=args.max_turns_per_chat,
                names_map_path=args.names_map,
                group_filter=args.group,
            )
            print(
                f"Exported {summary.exported_conversations}/{summary.total_conversations} "
                f"ChatGPT conversations across {len(summary.groups_written)} group(s) "
                f"to {summary.output_dir}"
            )
            return 0

        if args.command == "codex":
            summary = convert_codex_sessions(
                output_dir=args.output,
                sessions_dir=args.sessions_dir,
                archived_dir=args.archived_dir,
                extra_dirs=args.extra_dir,
                include_raw=args.include_raw,
                include_tool_calls=args.include_tool_calls,
                max_chars_per_turn=args.max_chars_per_turn,
            )
            print(
                f"Converted {summary.sessions_exported}/{summary.sessions_scanned} Codex sessions "
                f"({summary.active_sessions} active, {summary.archived_sessions} archived) "
                f"into {summary.projects_written} project(s) at {summary.output_dir} "
                f"(malformed lines skipped: {summary.malformed_lines_skipped})"
            )
            return 0

        if args.command == "distill":
            result = distill_memory(
                inputs=args.input,
                output_path=args.output,
                project_name=args.project,
                provider=args.provider,
                model=args.model,
                max_chars=args.max_chars,
                chunk_chars=args.chunk_chars,
                redact=not args.no_redact,
            )
            model_info = f" ({result.model})" if result.model else ""
            print(
                f"Distilled {len(result.source_files)} file(s) via {result.provider}{model_info} "
                f"[{result.chunks_processed} chunk(s), {result.secrets_redacted} secret(s) redacted] "
                f"-> {result.output_path}"
            )
            return 0

        if args.command == "vault-init":
            result = init_vault(
                vault_dir=args.vault,
                project=args.project,
                rules_dir=args.rules_dir,
                force=args.force,
            )
            print(
                f"Initialized vault at {result.vault_dir}: "
                f"{len(result.created)} created, {len(result.skipped)} skipped, "
                f"{len(result.archived)} archived"
            )
            return 0

        if args.command == "sync-vault":
            result = sync_to_vault(
                vault_dir=args.vault,
                source_path=args.source,
                project=args.project,
                distill=args.distill,
                provider=args.provider,
                model=args.model,
                archive_previous=not args.no_archive,
                write_handoff=args.write_handoff,
                agent=args.agent,
                redact=not args.no_redact,
            )
            print(
                f"Synced {len(result.synced_projects)} project(s) to {result.vault_dir} "
                f"(archived: {len(result.archived_files)}, handoffs: {len(result.handoffs_written)})"
            )
            return 0

    except (FileNotFoundError, ValueError, ProviderConfigError, ProviderRequestError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 2
