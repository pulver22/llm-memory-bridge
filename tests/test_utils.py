"""Unit tests for memory_bridge.utils."""

from __future__ import annotations

from pathlib import Path

from memory_bridge.utils import (
    ensure_unique_archive_path,
    format_timestamp,
    redact_secrets,
    slugify,
    strip_chatgpt_artifacts,
    truncate_text,
)


def test_slugify_normalizes_to_kebab_case() -> None:
    assert slugify("My Project (v2) / Alpha!") == "my-project-v2-alpha"
    assert slugify("   ---   ", fallback="default-slug") == "default-slug"
    assert slugify("", fallback="empty") == "empty"
    assert len(slugify("a-" * 60, max_len=20)) <= 20


def test_redact_secrets_masks_common_tokens() -> None:
    sample = (
        "OPENAI=sk-testabcdefghijklmnop "
        "ANTHROPIC=sk-ant-api03-1234567890abcdef "
        "GH=ghp_1234567890abcdef1234 "
        "GOOGLE=AIzaSyDummyKey1234567890 "
        "AUTH=Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig "
        "SAFE=normal-value"
    )
    redacted, count = redact_secrets(sample)
    assert count == 5
    assert "sk-test" not in redacted
    assert "sk-ant-" not in redacted
    assert "ghp_" not in redacted
    assert "AIza" not in redacted
    assert "eyJhbGci" not in redacted
    assert "Bearer [REDACTED]" in redacted
    assert "SAFE=normal-value" in redacted


def test_strip_chatgpt_artifacts_and_truncate() -> None:
    raw = "Result confirmed\ue200cite\ue202turn1search0\ue201.\n\n\n\nNext line\ue203."
    assert strip_chatgpt_artifacts(raw) == "Result confirmed.\n\nNext line."
    truncated = truncate_text("0123456789ABCDEF", 10)
    assert truncated.startswith("0123456789")
    assert "[truncated 6 chars]" in truncated
    assert truncate_text("short", 0) == "short"


def test_format_timestamp_and_archive_uniqueness(tmp_path: Path) -> None:
    assert format_timestamp(1760000000) == "2025-10-09 08:53 UTC"
    assert format_timestamp("2026-11-25T12:30:00Z") == "2026-11-25 12:30 UTC"
    assert format_timestamp(None) == "unknown"

    archive_dir = tmp_path / "Archive"
    p1 = ensure_unique_archive_path(archive_dir, "2026-11-25_note.md")
    p1.write_text("v1", encoding="utf-8")
    p2 = ensure_unique_archive_path(archive_dir, "2026-11-25_note.md")
    assert p2.name == "2026-11-25_note-2.md"
