"""Publisher registry. Default is 'assisted' (prepare-only, never auto-posts)."""
from __future__ import annotations

from trendengine.config import Config
from trendengine.publishers.assisted import AssistedPublisher
from trendengine.publishers.base import Publisher, PublishResult
from trendengine.publishers.meta_graph import MetaGraphPublisher
from trendengine.publishers.tiktok import TikTokPublisher
from trendengine.publishers.youtube_publisher import YouTubePublisher

PUBLISHER_REGISTRY: dict[str, type[Publisher]] = {
    AssistedPublisher.name: AssistedPublisher,
    YouTubePublisher.name: YouTubePublisher,
    MetaGraphPublisher.name: MetaGraphPublisher,
    TikTokPublisher.name: TikTokPublisher,
}


def get_publisher(config: Config, name: str | None = None) -> Publisher:
    name = name or config.publishing.get("default_publisher", "assisted")
    cls = PUBLISHER_REGISTRY.get(name, AssistedPublisher)
    return cls(config)


__all__ = ["Publisher", "PublishResult", "PUBLISHER_REGISTRY", "get_publisher"]
