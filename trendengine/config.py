"""Configuration loading: config.yaml (behaviour) + .env (secrets)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    """Thin wrapper over the parsed config.yaml plus process environment.

    Access whole sections as plain dicts (``cfg.sources``) so source/publisher
    plugins can read their own free-form settings without a rigid schema.
    """

    raw: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    @classmethod
    def load(cls, config_path: str | os.PathLike | None = None,
             env_path: str | os.PathLike | None = None) -> "Config":
        cfg_path = Path(config_path) if config_path else PROJECT_ROOT / "config.yaml"
        env_file = Path(env_path) if env_path else PROJECT_ROOT / ".env"
        # .env is optional — sources without creds just get skipped later.
        load_dotenv(env_file if env_file.exists() else None)
        with open(cfg_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls(raw=raw, path=cfg_path)

    # -- section accessors -------------------------------------------------
    @property
    def niche(self) -> dict: return self.raw.get("niche", {})
    @property
    def brand(self) -> dict: return self.raw.get("brand", {})
    @property
    def sources(self) -> dict: return self.raw.get("sources", {})
    @property
    def analysis(self) -> dict: return self.raw.get("analysis", {})
    @property
    def generation(self) -> dict: return self.raw.get("generation", {})
    @property
    def llm(self) -> dict: return self.raw.get("llm", {})
    @property
    def schedule(self) -> dict: return self.raw.get("schedule", {})
    @property
    def safety(self) -> dict: return self.raw.get("safety", {})
    @property
    def dashboard(self) -> dict: return self.raw.get("dashboard", {})
    @property
    def publishing(self) -> dict: return self.raw.get("publishing", {})

    @property
    def keywords(self) -> list[str]:
        return list(self.niche.get("keywords", []))

    # -- secrets -----------------------------------------------------------
    @staticmethod
    def env(key: str, default: str | None = None) -> str | None:
        return os.environ.get(key, default)

    def db_path(self) -> Path:
        return PROJECT_ROOT / "trendengine.sqlite3"
