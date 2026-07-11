"""Default LLM adapter: a local model served by Ollama (free, offline).

Talks to Ollama's REST API directly (no extra dependency). Install Ollama and
pull a model first — see the README:
    ollama pull llama3.1
"""
from __future__ import annotations

import requests

from trendengine.config import Config
from trendengine.llm.base import LLMClient, LLMError
from trendengine.logging_setup import get_logger

log = get_logger(__name__)


class OllamaClient(LLMClient):
    provider = "ollama"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.host = self.settings.get("host", "http://localhost:11434").rstrip("/")
        self.timeout = int(self.settings.get("timeout_seconds", 120))
        self.default_temperature = float(self.settings.get("temperature", 0.8))

    def generate(self, prompt: str, system: str | None = None,
                 temperature: float | None = None) -> str:
        payload = {
            "model": self.model or "llama3.1",
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.default_temperature if temperature is None else temperature,
            },
        }
        if system:
            payload["system"] = system
        try:
            resp = requests.post(
                f"{self.host}/api/generate", json=payload, timeout=self.timeout)
        except requests.exceptions.ConnectionError as exc:
            raise LLMError(
                f"Cannot reach Ollama at {self.host}. Is it running? "
                f"Start it with `ollama serve` and `ollama pull {self.model}`."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise LLMError(f"Ollama timed out after {self.timeout}s.") from exc

        if resp.status_code == 404:
            raise LLMError(
                f"Model '{self.model}' not found on Ollama. "
                f"Pull it: `ollama pull {self.model}`.")
        if resp.status_code != 200:
            raise LLMError(f"Ollama error {resp.status_code}: {resp.text[:300]}")
        return resp.json().get("response", "").strip()

    def health_check(self) -> tuple[bool, str]:
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            have = any((self.model or "").split(":")[0] in m for m in models)
            if not have:
                return False, (f"Ollama up but '{self.model}' not pulled. "
                              f"Run: ollama pull {self.model}")
            return True, f"ollama:{self.model} ready"
        except Exception as exc:  # noqa: BLE001
            return False, f"Ollama not reachable at {self.host}: {exc}"
