"""Source registry — add a new source by registering its class here.

To add your own source: subclass ``Source`` (see base.py), give it a unique
``name`` that matches a key under ``sources:`` in config.yaml, and register it
in ``SOURCE_REGISTRY`` below.
"""
from __future__ import annotations

from trendengine.config import Config
from trendengine.sources.base import MissingCredentials, Source, TrendItem
from trendengine.sources.google_trends import GoogleTrendsSource
from trendengine.sources.reddit_source import RedditSource
from trendengine.sources.rss_source import RSSSource
from trendengine.sources.youtube_source import YouTubeSource

SOURCE_REGISTRY: dict[str, type[Source]] = {
    RedditSource.name: RedditSource,
    GoogleTrendsSource.name: GoogleTrendsSource,
    YouTubeSource.name: YouTubeSource,
    RSSSource.name: RSSSource,
}


def build_sources(config: Config) -> list[Source]:
    """Instantiate every source that is present in config (enabled or not).

    ``Source.collect`` short-circuits disabled sources, so we build them all and
    let each decide whether to run.
    """
    sources: list[Source] = []
    for name, cls in SOURCE_REGISTRY.items():
        if name in config.sources:
            sources.append(cls(config))
    return sources


__all__ = [
    "Source", "TrendItem", "MissingCredentials",
    "SOURCE_REGISTRY", "build_sources",
]
