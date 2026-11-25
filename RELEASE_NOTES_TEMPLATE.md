# Release vX.Y.Z

## Highlights
- Brief 1–2 sentence summary of what this release ships.

## New Features
- Feature description (`#PR` / commit ref)

## Bug Fixes & Resilience
- Fix description (`#PR` / commit ref)

## Breaking Changes
- None (or list migration steps clearly).

## Upgrade & Verification Notes
```bash
pip install --upgrade llm-memory-bridge
memory-bridge --version
```

### Release Checklist
- [ ] Version bumped in `pyproject.toml` and `src/memory_bridge/__init__.py`
- [ ] `pytest -v` passes across Python 3.10–3.13
- [ ] CLI smoke tests verified (`export`, `codex`, `distill`, `vault-init`, `sync-vault`)
- [ ] `README.md` and `RELEASE_NOTES_TEMPLATE.md` reviewed
