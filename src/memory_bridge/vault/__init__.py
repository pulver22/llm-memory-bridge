"""Obsidian vault scaffolding, cross-agent rules, and sync helpers."""

from __future__ import annotations

from memory_bridge.vault.scaffold import VaultInitResult, init_vault
from memory_bridge.vault.sync import SyncResult, rebuild_projects_index, sync_to_vault

__all__ = [
    "SyncResult",
    "VaultInitResult",
    "init_vault",
    "rebuild_projects_index",
    "sync_to_vault",
]
