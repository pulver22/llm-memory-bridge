"""Unit tests for extractive distillation, LLM providers, and map-reduce synthesis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from memory_bridge.distill.extractive import REQUIRED_SECTIONS
from memory_bridge.distill.providers import (
    AnthropicProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    ProviderConfigError,
    get_provider,
)
from memory_bridge.distill.synthesizer import distill_memory


def test_distill_extractive_produces_four_sections_and_redacts_secrets(tmp_path: Path) -> None:
    src = tmp_path / "PROJECT_MEMORY.md"
    src.write_text(
        """# Alpha — Project Memory

## Architecture Chat
- We decided to use FastAPI with SQLite WAL mode for local persistence.
- Currently implementing the CLI export command and passing unit tests.
- API key leaked in log: sk-testabcdefghijklmnop must not survive redaction.
- The worker service must listen on port 8080 with a 30s timeout constraint.
- Open question: Should we add automated Syncthing conflict detection next?
- Thanks!
""",
        encoding="utf-8",
    )
    out = tmp_path / "project_prior_context.md"
    result = distill_memory(inputs=[src], output_path=out, project_name="Alpha App")

    assert result.provider == "extractive"
    assert result.secrets_redacted == 1
    assert out.is_file()

    content = out.read_text(encoding="utf-8")
    assert "sk-test" not in content
    assert "[REDACTED]" in content
    for section in REQUIRED_SECTIONS:
        assert f"## {section}" in content
    assert "FastAPI with SQLite WAL mode" in content
    assert "Syncthing conflict detection" in content


def test_provider_missing_env_vars_raise_clear_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ProviderConfigError, match="OPENAI_API_KEY"):
        get_provider("openai")
    with pytest.raises(ProviderConfigError, match="GEMINI_API_KEY"):
        get_provider("gemini")
    with pytest.raises(ProviderConfigError, match="ANTHROPIC_API_KEY"):
        get_provider("anthropic")


def test_all_llm_provider_adapters_mocked_http() -> None:
    captured: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    def fake_openai(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        captured.append((url, headers, payload))
        return {"choices": [{"message": {"content": "## Finalised Decisions & Architecture\n- OpenAI ok"}}]}

    def fake_ollama(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        captured.append((url, headers, payload))
        return {"message": {"content": "## Active Work & Current State\n- Ollama ok"}}

    def fake_gemini(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        captured.append((url, headers, payload))
        return {"candidates": [{"content": {"parts": [{"text": "## Key Facts, Constraints & Parameters\n- Gemini ok"}]}}]}

    def fake_anthropic(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        captured.append((url, headers, payload))
        return {"content": [{"type": "text", "text": "## Open Questions & Next Steps\n- Anthropic ok"}]}

    p1 = OpenAICompatibleProvider(api_key="k1", http_post=fake_openai)
    assert "OpenAI ok" in p1.complete("sys", "usr")
    assert captured[-1][1]["Authorization"] == "Bearer k1"

    p2 = OllamaProvider(host="http://localhost:11434", http_post=fake_ollama)
    assert "Ollama ok" in p2.complete("sys", "usr")
    assert captured[-1][0].endswith("/api/chat")

    p3 = GeminiProvider(api_key="g1", http_post=fake_gemini)
    assert "Gemini ok" in p3.complete("sys", "usr")
    assert captured[-1][1]["x-goog-api-key"] == "g1"

    p4 = AnthropicProvider(api_key="a1", http_post=fake_anthropic)
    assert "Anthropic ok" in p4.complete("sys", "usr")
    assert captured[-1][1]["x-api-key"] == "a1"


def test_distill_memory_map_reduce_chunking(tmp_path: Path) -> None:
    src = tmp_path / "large.md"
    src.write_text(("Paragraph about architecture decisions.\n\n" * 40), encoding="utf-8")

    calls: list[str] = []

    class FakeLLM:
        provider_name = "ollama"
        model = "llama3.2"

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            calls.append(user_prompt)
            return (
                "## Finalised Decisions & Architecture\n- Chunk decision.\n\n"
                "## Active Work & Current State\n- Active step.\n\n"
                "## Key Facts, Constraints & Parameters\n- Port 8080.\n\n"
                "## Open Questions & Next Steps\n- Verify sync."
            )

    res = distill_memory(
        inputs=[src],
        project_name="Large Project",
        chunk_chars=300,
        provider_instance=FakeLLM(),
    )
    assert res.chunks_processed >= 3
    # N map calls + 1 reduce call
    assert len(calls) == res.chunks_processed + 1
    for section in REQUIRED_SECTIONS:
        assert f"## {section}" in res.content
