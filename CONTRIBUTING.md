# Contributing to `llm-memory-bridge`

Thank you for your interest in contributing! `llm-memory-bridge` is a zero-dependency Python CLI for turning ChatGPT exports and Codex session rollouts into compact, model-agnostic Markdown memory and structured Obsidian vaults.

## Local Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

## Strict Privacy & Fixture Policy

- **Never commit real chat exports, personal Codex rollouts, Obsidian vaults, or credentials.**
- All test fixtures in `tests/` must use **100% synthetic, anonymized data**.
- Never read `~/.codex`, `~/Documents`, or real user directories during unit tests; use `tmp_path` fixtures instead.
- Never hardcode API keys or tokens anywhere in code, docs, or tests.

## Code Guidelines

- Target **Python 3.10+** with **zero external runtime dependencies** (standard library only).
- Keep functions modular, typed (`from __future__ import annotations`), and well-documented.
- Use timezone-aware UTC timestamps (`datetime.now(timezone.utc)`).
- Any new CLI option or behavior should include unit tests and a `README.md` update if user-facing.

## Pull Request Checklist

- [ ] `pytest -v` passes locally with zero failures and zero warnings.
- [ ] All fixtures are synthetic and anonymized.
- [ ] `git status` contains no `.env`, `.zip`, `conversations*.json`, `*.jsonl`, or memory dump directories.
- [ ] Documentation (`README.md`) reflects any new flags or commands.
