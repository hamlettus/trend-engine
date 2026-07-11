"""Publisher plugin contract.

A publisher NEVER posts on its own. It *prepares* an approved draft so you can
post it yourself (assisted), or — if you wire up an official API adapter later —
performs the post only when you explicitly trigger it from the dashboard.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass

from trendengine.config import Config
from trendengine.db.models import Draft


@dataclass
class PublishResult:
    ok: bool
    message: str
    export_path: str | None = None
    external_post_id: str | None = None


class Publisher(abc.ABC):
    name: str = "base"

    def __init__(self, config: Config) -> None:
        self.config = config
        self.settings: dict = config.publishing

    @abc.abstractmethod
    def prepare(self, draft: Draft) -> PublishResult:
        """Prepare an approved draft for posting (copy/export/open)."""
        raise NotImplementedError

    def publish(self, draft: Draft) -> PublishResult:
        """Actually post via an official API. Assisted publisher does not do this.

        Only ever called on explicit user action from the dashboard.
        """
        raise NotImplementedError(
            f"Publisher '{self.name}' does not implement direct publishing.")
