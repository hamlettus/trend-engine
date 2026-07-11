"""Swappable LLM layer. Ollama is the free/local default; Anthropic is opt-in.

Swap providers by editing ``llm.provider`` in config.yaml — no code changes.
"""
from __future__ import annotations

from trendengine.config import Config
from trendengine.llm.base import LLMClient, LLMError


def get_llm(config: Config) -> LLMClient:
    provider = (config.llm.get("provider", "ollama") or "ollama").lower()
    if provider == "ollama":
        from trendengine.llm.ollama_client import OllamaClient
        return OllamaClient(config)
    if provider == "anthropic":
        from trendengine.llm.anthropic_client import AnthropicClient
        return AnthropicClient(config)
    raise LLMError(f"Unknown llm.provider '{provider}' (use 'ollama' or 'anthropic').")


__all__ = ["LLMClient", "LLMError", "get_llm"]
