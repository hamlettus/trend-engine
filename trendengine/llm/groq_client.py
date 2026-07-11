"""Groq LLM adapter — free hosted inference (no local RAM needed).

Groq's API is OpenAI-compatible and has a genuinely free tier, which makes it a
great fit when you can't/don't want to run Ollama locally — e.g. a tiny cheap
server instead of one big enough for an 8B model. Get a free key at
https://console.groq.com/keys and put it in .env as GROQ_API_KEY.

Switch to it with `llm.provider: groq` in config.yaml — nothing else changes,
since the drafter/gate/clipper all talk to the LLMClient interface.
"""
from __future__ import annotations

import requests

from trendengine.config import Config
from trendengine.llm.base import LLMClient, LLMError
from trendengine.logging_setup import get_logger

log = get_logger(__name__)


class GroqClient(LLMClient):
    provider = "groq"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.host = self.settings.get("host", "https://api.groq.com/openai/v1").rstrip("/")
        self.timeout = int(self.settings.get("timeout_seconds", 60))
        self.default_temperature = float(self.settings.get("temperature", 0.8))
        self.api_key = Config.env("GROQ_API_KEY")

    def generate(self, prompt: str, system: str | None = None,
                 temperature: float | None = None) -> str:
        if not self.api_key:
            raise LLMError(
                "GROQ_API_KEY not set. Add it to .env (free key from "
                "https://console.groq.com/keys), or keep llm.provider = ollama.")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model or "llama-3.1-8b-instant",
            "messages": messages,
            "temperature": self.default_temperature if temperature is None else temperature,
        }
        try:
            resp = requests.post(
                f"{self.host}/chat/completions", json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout)
        except requests.exceptions.ConnectionError as exc:
            raise LLMError(f"Cannot reach Groq at {self.host}.") from exc
        except requests.exceptions.Timeout as exc:
            raise LLMError(f"Groq timed out after {self.timeout}s.") from exc

        if resp.status_code == 401:
            raise LLMError("Groq rejected the API key (401). Check GROQ_API_KEY.")
        if resp.status_code == 429:
            raise LLMError("Groq rate limit hit (429). Wait a moment or slow the cadence.")
        if resp.status_code != 200:
            raise LLMError(f"Groq error {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Unexpected Groq response: {resp.text[:200]}") from exc

    def health_check(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "GROQ_API_KEY not set (free: console.groq.com/keys)"
        try:
            resp = requests.get(
                f"{self.host}/models",
                headers={"Authorization": f"Bearer {self.api_key}"}, timeout=10)
            if resp.status_code == 401:
                return False, "GROQ_API_KEY rejected (401)"
            resp.raise_for_status()
            return True, f"groq:{self.model or 'llama-3.1-8b-instant'} ready"
        except Exception as exc:  # noqa: BLE001
            return False, f"Groq not reachable: {exc}"
