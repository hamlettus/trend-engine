"""Local, free vertical-video generation for YouTube Shorts."""


class MediaError(RuntimeError):
    """Raised when video/audio tooling is missing or rendering fails."""


from trendengine.media.short import ShortGenerator  # noqa: E402

__all__ = ["ShortGenerator", "MediaError"]
