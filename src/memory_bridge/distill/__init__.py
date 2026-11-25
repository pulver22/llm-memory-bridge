"""Distillation and pluggable LLM synthesis adapters."""

from __future__ import annotations

from memory_bridge.distill.extractive import REQUIRED_SECTIONS, distill_extractive
from memory_bridge.distill.providers import (
    AnthropicProvider,
    GeminiProvider,
    LLMProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    ProviderConfigError,
    ProviderRequestError,
    get_provider,
)
from memory_bridge.distill.synthesizer import DistillResult, distill_memory

__all__ = [
    "AnthropicProvider",
    "DistillResult",
    "GeminiProvider",
    "LLMProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "ProviderConfigError",
    "ProviderRequestError",
    "REQUIRED_SECTIONS",
    "distill_extractive",
    "distill_memory",
    "get_provider",
]
