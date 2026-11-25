"""Shared formatting, slugification, secret redaction, and safe file helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

_CHATGPT_CITATION_BLOCK_RE = re.compile(r"\ue200[^\ue201]*\ue201")
_CHATGPT_PRIVATE_USE_RE = re.compile(r"[\ue200-\ue206]")
_MULTI_BLANK_LINES_RE = re.compile(r"\n{3,}")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        re.MULTILINE,
    ),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bsk-(?:proj-|svcacct-|test-)?[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}\b", re.IGNORECASE),
)


def slugify(value: str | None, fallback: str = "untitled", max_len: int = 80) -> str:
    """Convert an arbitrary string into a safe kebab-case filesystem slug."""
    if not value:
        return fallback
    normalized = value.strip().lower()
    slug = _NON_ALNUM_RE.sub("-", normalized).strip("-")
    if not slug:
        return fallback
    if max_len > 0 and len(slug) > max_len:
        slug = slug[:max_len].rstrip("-") or fallback
    return slug


def today_iso() -> str:
    """Return the current UTC date formatted as YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def utc_now_iso() -> str:
    """Return the current UTC timestamp formatted as ISO-8601."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_timestamp(ts: float | int | str | None) -> str:
    """Format a Unix epoch or ISO-8601 timestamp to 'YYYY-MM-DD HH:MM UTC'."""
    if ts is None or ts == "":
        return "unknown"
    if isinstance(ts, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        except (ValueError, OSError, OverflowError):
            return "unknown"
    if isinstance(ts, str):
        stripped = ts.strip()
        try:
            numeric = float(stripped)
            dt = datetime.fromtimestamp(numeric, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            pass
        iso_candidate = stripped[:-1] + "+00:00" if stripped.endswith("Z") else stripped
        try:
            dt = datetime.fromisoformat(iso_candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            return "unknown"
    return "unknown"


def strip_chatgpt_artifacts(text: str) -> str:
    """Remove ChatGPT private-use citation markers and collapse excess blank lines."""
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _CHATGPT_CITATION_BLOCK_RE.sub("", cleaned)
    cleaned = _CHATGPT_PRIVATE_USE_RE.sub("", cleaned)
    cleaned = _MULTI_BLANK_LINES_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate text cleanly when max_chars > 0, appending omitted char count."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    head = text[:max_chars].rstrip()
    return f"{head}\n… [truncated {omitted} chars]"


def redact_secrets(text: str) -> tuple[str, int]:
    """Redact common API keys, bearer tokens, and PEM private keys from text."""
    if not text:
        return text, 0
    total_count = 0
    redacted = text
    for pattern in _SECRET_PATTERNS:
        def _replace(match: re.Match[str]) -> str:
            nonlocal total_count
            total_count += 1
            matched = match.group(0)
            if matched.lower().startswith("bearer "):
                return "Bearer [REDACTED]"
            return "[REDACTED]"

        redacted = pattern.sub(_replace, redacted)
    return redacted, total_count


def ensure_unique_archive_path(archive_dir: Path, filename: str) -> Path:
    """Return a non-colliding path inside archive_dir for archival writes."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    candidate = archive_dir / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while True:
        numbered = archive_dir / f"{stem}-{counter}{suffix}"
        if not numbered.exists():
            return numbered
        counter += 1
