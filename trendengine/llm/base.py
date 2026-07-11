"""LLM client interface. Implement ``generate`` to add a new provider."""
from __future__ import annotations

import abc

from trendengine.config import Config


class LLMError(RuntimeError):
    """Raised for any LLM backend failure (connection, auth, bad response)."""


class LLMClient(abc.ABC):
    provider: str = "base"

    def __init__(self, config: Config) -> None:
        self.config = config
        self.settings: dict = config.llm.get(self.provider, {})

    @property
    def model(self) -> str:
        return self.settings.get("model", "")

    @abc.abstractmethod
    def generate(self, prompt: str, system: str | None = None,
                 temperature: float | None = None) -> str:
        """Return the model's text completion for ``prompt``."""
        raise NotImplementedError

    def health_check(self) -> tuple[bool, str]:
        """Best-effort readiness probe. Override where cheap to do so."""
        return True, f"{self.provider}:{self.model}"
