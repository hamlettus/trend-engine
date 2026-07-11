"""Anthropic (Claude) LLM adapter — OPT-IN, disabled by default.

This keeps the engine 100%% free out of the box. To enable Claude later:

  1. `pip install anthropic`
  2. Put ANTHROPIC_API_KEY in your .env  (https://console.anthropic.com/)
  3. In config.yaml set:
         llm:
           provider: anthropic
           anthropic:
             model: claude-sonnet-5

Nothing else in the app changes — the drafter talks to the LLMClient interface.
The implementation below is complete but intentionally gated so you don't incur
cost unless you deliberately switch to it.
"""
from __future__ import annotations

from trendengine.config import Config
from trendengine.llm.base import LLMClient, LLMError
from trendengine.logging_setup import get_logger

log = get_logger(__name__)


class AnthropicClient(LLMClient):
    provider = "anthropic"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.api_key = Config.env("ANTHROPIC_API_KEY")
        self.max_tokens = int(self.settings.get("max_tokens", 1024))
        self.default_temperature = float(self.settings.get("temperature", 0.8))
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY not set. Add it to .env, or keep "
                "llm.provider = ollama to stay free/local.")
        try:
            import anthropic
        except ImportError as exc:
            raise LLMError(
                "The 'anthropic' package isn't installed. Run "
                "`pip install anthropic` to enable the Claude adapter.") from exc
        self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def generate(self, prompt: str, system: str | None = None,
                 temperature: float | None = None) -> str:
        client = self._get_client()
        try:
            message = client.messages.create(
                model=self.model or "claude-sonnet-5",
                max_tokens=self.max_tokens,
                temperature=self.default_temperature if temperature is None else temperature,
                system=system or "",
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001 - surface as a uniform LLMError
            raise LLMError(f"Anthropic request failed: {exc}") from exc
        # Concatenate text blocks from the response.
        return "".join(
            block.text for block in message.content
            if getattr(block, "type", "") == "text"
        ).strip()

    def health_check(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "ANTHROPIC_API_KEY not set"
        try:
            self._get_client()
        except LLMError as exc:
            return False, str(exc)
        return True, f"anthropic:{self.model} ready"
