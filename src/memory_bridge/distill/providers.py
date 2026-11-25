"""Pluggable LLM synthesis providers using Python stdlib HTTP and env vars."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

HttpPostFn = Callable[[str, dict[str, str], dict[str, Any], int], dict[str, Any]]


class ProviderConfigError(ValueError):
    """Raised when required provider configuration or environment variables are missing."""


class ProviderRequestError(RuntimeError):
    """Raised when an LLM HTTP request fails or returns an unexpected response."""


class LLMProvider(Protocol):
    """Protocol implemented by all synthesis providers."""

    provider_name: str
    model: str

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Send a prompt pair and return generated Markdown text."""


def default_http_post(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int = 120,
) -> dict[str, Any]:
    """Perform a JSON POST request using urllib.request."""
    body = json.dumps(payload).encode("utf-8")
    merged_headers = {"Content-Type": "application/json", **headers}
    req = urllib.request.Request(url, data=body, headers=merged_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderRequestError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderRequestError(f"Network error contacting {url}: {exc.reason}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderRequestError(f"Invalid JSON response from {url}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ProviderRequestError(f"Unexpected JSON payload type from {url}")
    return parsed


def _is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


class OpenAICompatibleProvider:
    """Adapter for OpenAI and OpenAI-compatible chat completions endpoints."""

    provider_name = "openai"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 120,
        http_post: HttpPostFn | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "").strip()
        if not self.api_key and not _is_local_url(self.base_url):
            raise ProviderConfigError(
                "OPENAI_API_KEY environment variable is required for provider 'openai' "
                "(or set OPENAI_BASE_URL to a local server)."
            )
        self.model = model or os.environ.get("MEMORY_BRIDGE_MODEL") or "gpt-4o-mini"
        self.timeout = timeout
        self._post = http_post or default_http_post

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        data = self._post(url, headers, payload, self.timeout)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderRequestError("OpenAI-compatible response missing 'choices'.")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ProviderRequestError("OpenAI-compatible response missing message content.")
        return content.strip()


class OllamaProvider:
    """Adapter for local Ollama /api/chat synthesis."""

    provider_name = "ollama"

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        timeout: int = 180,
        http_post: HttpPostFn | None = None,
    ) -> None:
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        self.model = model or os.environ.get("MEMORY_BRIDGE_MODEL") or "llama3.2"
        self.timeout = timeout
        self._post = http_post or default_http_post

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.host}/api/chat"
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        data = self._post(url, {}, payload, self.timeout)
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else data.get("response")
        if not isinstance(content, str) or not content.strip():
            raise ProviderRequestError("Ollama response missing 'message.content'.")
        return content.strip()


class GeminiProvider:
    """Adapter for Google Gemini generateContent REST API."""

    provider_name = "gemini"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: int = 120,
        http_post: HttpPostFn | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "").strip()
        if not self.api_key:
            raise ProviderConfigError("GEMINI_API_KEY environment variable is required for provider 'gemini'.")
        self.model = model or os.environ.get("MEMORY_BRIDGE_MODEL") or "gemini-2.5-flash"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._post = http_post or default_http_post

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": self.api_key}
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.1},
        }
        data = self._post(url, headers, payload, self.timeout)
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProviderRequestError("Gemini response missing 'candidates'.")
        content_obj = candidates[0].get("content") if isinstance(candidates[0], dict) else None
        parts = content_obj.get("parts") if isinstance(content_obj, dict) else None
        if not isinstance(parts, list) or not parts:
            raise ProviderRequestError("Gemini response missing content parts.")
        text = "\n".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()
        if not text:
            raise ProviderRequestError("Gemini response returned empty text.")
        return text


class AnthropicProvider:
    """Adapter for Anthropic Messages API."""

    provider_name = "anthropic"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com/v1",
        timeout: int = 120,
        http_post: HttpPostFn | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not self.api_key:
            raise ProviderConfigError("ANTHROPIC_API_KEY environment variable is required for provider 'anthropic'.")
        self.model = model or os.environ.get("MEMORY_BRIDGE_MODEL") or "claude-3-5-haiku-latest"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._post = http_post or default_http_post

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": 0.1,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        data = self._post(url, headers, payload, self.timeout)
        blocks = data.get("content")
        if not isinstance(blocks, list) or not blocks:
            raise ProviderRequestError("Anthropic response missing 'content'.")
        text = "\n".join(
            str(b.get("text", ""))
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
        if not text:
            raise ProviderRequestError("Anthropic response returned empty text.")
        return text


SUPPORTED_PROVIDERS = ("extractive", "openai", "ollama", "gemini", "anthropic")


def get_provider(
    name: str,
    model: str | None = None,
    http_post: HttpPostFn | None = None,
) -> LLMProvider:
    """Instantiate an LLM synthesis provider by name."""
    normalized = name.strip().lower()
    if normalized == "openai":
        return OpenAICompatibleProvider(model=model, http_post=http_post)
    if normalized == "ollama":
        return OllamaProvider(model=model, http_post=http_post)
    if normalized == "gemini":
        return GeminiProvider(model=model, http_post=http_post)
    if normalized == "anthropic":
        return AnthropicProvider(model=model, http_post=http_post)
    raise ProviderConfigError(
        f"Unsupported LLM provider '{name}'. Choose one of: {', '.join(SUPPORTED_PROVIDERS)}"
    )
