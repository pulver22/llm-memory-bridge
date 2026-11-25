# `llm-memory-bridge` (`memory-bridge`)

A model-agnostic, zero-dependency Python CLI for exporting ChatGPT archives and local Codex session rollouts into compact Markdown, distilling noisy transcripts into high-signal project memory, and synchronizing an Obsidian vault with cross-agent rules (`AGENTS.md`, `CLAUDE.md`, `.plans/template.md`) for Claude Code, Codex, and Antigravity (`agy`).

---

## Why `memory-bridge`?

- **Prunes noise, not history:** ChatGPT exports store full edit trees (`mapping`), hidden system prompts, and citation tokens. `memory-bridge export` walks only the active conversation chain from `current_node` back to root.
- **Resilient Codex extraction:** `memory-bridge codex` scans `~/.codex/sessions` and `~/.codex/archived_sessions`, skips malformed/truncated JSONL lines safely with a summary count, and groups transcripts by project `cwd`.
- **Save frontier tokens:** `memory-bridge distill` supports a zero-cost deterministic extractive mode AND pluggable local/external LLM providers (Ollama, OpenAI-compatible, Gemini, Anthropic) to condense huge histories into a crisp 4-section `project_prior_context.md`.
- **Shared agent memory:** `vault-init` and `sync-vault` maintain an LLM-agnostic Obsidian vault (`00_Index/`, `01_Projects/`, `02_Cross_Model_Handoffs/`, `Archive/`) and generate `AGENTS.md` / `CLAUDE.md` (`@AGENTS.md`) / `.plans/template.md` so any coding agent picks up where the last model left off.
- **Zero external runtime dependencies:** Built purely on the Python 3.10+ standard library.

---

## Architecture

```text
ChatGPT export (.zip / conversations*.json) ──► memory-bridge export ──► PROJECT_MEMORY.md + INDEX.md
Codex rollouts (~/.codex/{sessions,archived}) ► memory-bridge codex  ──► CODEX_PROJECT_MEMORY.md + INDEX.md
                                                                              │
                                                                              ▼
Obsidian Vault ◄── memory-bridge sync-vault ◄── project_prior_context.md ◄── memory-bridge distill
  ├── 00_Index/ (README.md, PROJECTS.md, HANDOFF_TEMPLATE.md)                  (extractive | ollama |
  ├── 01_Projects/<slug>/project_prior_context.md                               openai | gemini | anthropic)
  ├── 02_Cross_Model_Handoffs/YYYY-MM-DD_<project>_<agent>.md
  └── Archive/ (superseded notes moved here, never deleted)
```

---

## Installation

### From source (editable or standard)

```bash
git clone https://github.com/pulver22/llm-memory-bridge.git
cd llm-memory-bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Isolated CLI install with `pipx`

```bash
pipx install .
```

Both `memory-bridge` and `llm-memory-bridge` (plus `python -m memory_bridge`) are installed as entrypoints.

---

## CLI Quickstart & Examples

### 1. Export a ChatGPT archive (`export`)

Supports a downloaded ChatGPT `.zip` export, an extracted directory containing `conversations*.json` (including sharded `conversations-000.json`, `conversations-001.json`), or a single JSON file.

```bash
memory-bridge export \
  --input ~/Downloads/chatgpt-export.zip \
  --output ./chatgpt_memory_export
```

Optional flags:
- `--names-map names.json` — JSON file mapping `g-p-...` or `g-...` IDs to human-readable Project/GPT names.
- `--include-raw` — also write full per-conversation Markdown files under `<group>/raw/`.
- `--include-tools` — include tool role messages.
- `--max-chars-per-turn 1200` — cap turn length in compact `PROJECT_MEMORY.md` (`0` disables truncation).
- `--group projects` — filter to `all`, `projects`, `gpts`, `codex`, or `standalone`.

### 2. Convert local Codex rollouts (`codex`)

Recursively scans `~/.codex/sessions` and `~/.codex/archived_sessions` for `rollout-*.jsonl`, groups sessions by working directory (`cwd`), deduplicates duplicate event turns, and skips truncated/malformed JSONL lines safely:

```bash
memory-bridge codex \
  --output ./codex_sessions_markdown
```

Custom directories or raw output:

```bash
memory-bridge codex \
  --sessions-dir ~/.codex/sessions \
  --archived-dir ~/.codex/archived_sessions \
  --extra-dir ~/backups/codex_sessions \
  --output ./codex_sessions_markdown \
  --include-raw
```

### 3. Distill transcripts into `project_prior_context.md` (`distill`)

Produces a 4-section Markdown note:
1. `Finalised Decisions & Architecture`
2. `Active Work & Current State`
3. `Key Facts, Constraints & Parameters`
4. `Open Questions & Next Steps`

**Zero-cost deterministic extractive mode (default):**

```bash
memory-bridge distill \
  --input ./chatgpt_memory_export/projects/my-app/PROJECT_MEMORY.md \
          ./codex_sessions_markdown/my-app/CODEX_PROJECT_MEMORY.md \
  --project "My App" \
  --output ./project_prior_context.md
```

**Local LLM synthesis via Ollama (zero frontier token cost):**

```bash
export OLLAMA_HOST="http://localhost:11434"
memory-bridge distill \
  --input ./chatgpt_memory_export/projects/my-app/PROJECT_MEMORY.md \
  --project "My App" \
  --provider ollama \
  --model llama3.2 \
  --output ./project_prior_context.md
```

**External LLM providers (configured strictly via environment variables):**

| Provider | `--provider` | Required Env Var(s) | Optional Env Var(s) | Default Model |
| :--- | :--- | :--- | :--- | :--- |
| Deterministic | `extractive` | None | — | — |
| Ollama (local) | `ollama` | None | `OLLAMA_HOST` (`http://localhost:11434`) | `llama3.2` |
| OpenAI-compatible | `openai` | `OPENAI_API_KEY` | `OPENAI_BASE_URL` (`https://api.openai.com/v1`) | `gpt-4o-mini` |
| Gemini | `gemini` | `GEMINI_API_KEY` | — | `gemini-2.5-flash` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | — | `claude-3-5-haiku-latest` |

Large inputs exceeding `--chunk-chars` (default `48000`) automatically run map-reduce chunked synthesis. Common secret patterns are redacted before distillation/upload by default (`--no-redact` disables this).

### 4. Initialize an Obsidian Vault & Cross-Agent Rules (`vault-init`)

```bash
memory-bridge vault-init \
  --vault ~/Obsidian/AgentMemory \
  --project my-app \
  --rules-dir ~/projects/my-app
```

This scaffolds:
- `~/Obsidian/AgentMemory/00_Index/` (`README.md`, `PROJECTS.md`, `HANDOFF_TEMPLATE.md`, `templates/`)
- `~/Obsidian/AgentMemory/01_Projects/my-app/project_prior_context.md`
- `~/Obsidian/AgentMemory/02_Cross_Model_Handoffs/`
- `~/Obsidian/AgentMemory/Archive/`
- In `--rules-dir`: `AGENTS.md`, `CLAUDE.md` (with `@AGENTS.md`), and `.plans/template.md`

### 5. Sync Memory into the Obsidian Vault (`sync-vault`)

Sync a single distilled file, a project directory, or an entire multi-project export/codex tree:

```bash
memory-bridge sync-vault \
  --vault ~/Obsidian/AgentMemory \
  --source ./codex_sessions_markdown \
  --distill \
  --write-handoff \
  --agent codex
```

When `01_Projects/<slug>/project_prior_context.md` already exists and its content changes, `sync-vault` archives the superseded copy to `Archive/YYYY-MM-DD_<slug>_project_prior_context.md` instead of deleting it, and rebuilds `00_Index/PROJECTS.md`.

---

## Multi-Machine Setup: Obsidian + Syncthing

`llm-memory-bridge` pairs naturally with **Obsidian** + **Syncthing** across laptops and workstations:

1. **Keep one canonical vault directory** (for example `~/Obsidian/AgentMemory`) synced via Syncthing across machines.
2. **Use a `.stignore` file** inside your vault root to prevent Obsidian UI state churn and sync conflicts:
   ```text
   .obsidian/workspace*.json
   .obsidian/cache
   .trash/
   .DS_Store
   ```
3. **Avoid concurrent edits on the same handoff file:** Name handoffs with date, project, and agent (`YYYY-MM-DD_<project>_<agent>.md`), so different machines/agents append distinct handoff notes rather than colliding.
4. **Archive, never delete:** Superseded `project_prior_context.md` versions are moved to `Archive/` with dates so Syncthing history remains recoverable.

---

## Privacy & Security Guidelines

- **Never commit raw exports or vaults:** `.gitignore` excludes `conversations*.json`, `*.zip`, `*.jsonl`, `.env`, `chatgpt_memory_export/`, `codex_sessions_markdown/`, `claude_compact_memory/`, and `local_vault/`.
- **Environment-variable credentials only:** API keys are read exclusively from environment variables (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`). Never store keys inside `AGENTS.md`, `CLAUDE.md`, handoff notes, or `.plans/`.
- **Default secret redaction:** `distill` redacts common credential formats (API keys, Bearer tokens, PEM private keys) before writing output or calling an LLM provider.
- **Local-first option:** Use `--provider extractive` or `--provider ollama` when working with sensitive histories that should never leave your machine.

---

## Development & Testing

```bash
pytest -v
```

All tests use synthetic, anonymized fixtures and never read your real `~/.codex` directory or personal exports. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and [LICENSE](LICENSE) for MIT license terms.
