"""Source plugin contract + the TrendItem value object."""
from __future__ import annotations

import abc
import datetime as dt
from dataclasses import dataclass, field

from trendengine.config import Config
from trendengine.logging_setup import get_logger
from trendengine.utils.hashing import content_hash
from trendengine.utils.ratelimit import LIMITER

log = get_logger(__name__)


@dataclass
class TrendItem:
    """One discovered piece of trending content, normalised across sources."""
    source: str
    external_id: str
    title: str
    url: str
    score: float                     # raw engagement signal (upvotes, views, interest…)
    created_at: dt.datetime
    keyword: str = ""                # niche keyword that matched
    engagement: dict = field(default_factory=dict)  # per-source raw metrics
    extra: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return content_hash(self.source, self.title, self.url)


class Source(abc.ABC):
    """Base class for a pluggable trend source.

    Subclasses set ``name`` and implement :meth:`fetch`. Rate limiting and the
    enabled flag are handled here so every source behaves consistently.
    """

    name: str = "base"

    def __init__(self, config: Config) -> None:
        self.config = config
        self.settings: dict = config.sources.get(self.name, {})

    def is_enabled(self) -> bool:
        return bool(self.settings.get("enabled", False))

    def min_interval(self) -> float:
        return float(self.settings.get("min_interval_seconds", 60))

    def rate_ok(self) -> bool:
        return LIMITER.ready(f"source:{self.name}", self.min_interval())

    def collect(self, keywords: list[str]) -> list[TrendItem]:
        """Public entry point: enforces enabled + rate limit, then fetches."""
        if not self.is_enabled():
            return []
        if not self.rate_ok():
            return []
        try:
            items = self.fetch(keywords)
            log.info("[%s] fetched %d items", self.name, len(items))
            return items
        except MissingCredentials as exc:
            log.warning("[%s] skipped — %s", self.name, exc)
            return []
        except Exception as exc:  # noqa: BLE001 - one bad source shouldn't kill the run
            log.error("[%s] fetch failed: %s", self.name, exc)
            return []

    @abc.abstractmethod
    def fetch(self, keywords: list[str]) -> list[TrendItem]:
        """Return trending items for the given niche keywords."""
        raise NotImplementedError


class MissingCredentials(RuntimeError):
    """Raised by a source when required API keys are absent (soft-skip)."""
