"""Rate limiting and robots.txt compliance for polite discovery."""
from __future__ import annotations

import threading
import time
import urllib.robotparser
from urllib.parse import urlparse

from trendengine.logging_setup import get_logger

log = get_logger(__name__)


class RateLimiter:
    """Simple per-key minimum-interval gate, safe across threads.

    A source calls :meth:`ready` before fetching; if it returns False the
    scheduler skips that source this cycle (it will be due on a later cycle).
    """

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def ready(self, key: str, min_interval_seconds: float) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key)
            # First-ever call for a key is always allowed (don't rely on the
            # absolute monotonic value, which is small right after boot).
            if last is None or now - last >= min_interval_seconds:
                self._last[key] = now
                return True
        wait = min_interval_seconds - (now - last)
        log.info("Rate limit: '%s' not due for %.0fs", key, wait)
        return False


# Module-level shared limiter so every source instance in a process cooperates.
LIMITER = RateLimiter()


_ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser] = {}
_ROBOTS_LOCK = threading.Lock()


def robots_allows(url: str, user_agent: str = "trend-engine") -> bool:
    """Return True if ``url`` may be fetched per the host's robots.txt.

    Fails open (returns True) if robots.txt can't be fetched — matching the
    behaviour of most well-behaved crawlers, while still honouring explicit
    Disallow rules when they are reachable.
    """
    try:
        parts = urlparse(url)
        if not parts.scheme or not parts.netloc:
            return True
        base = f"{parts.scheme}://{parts.netloc}"
        with _ROBOTS_LOCK:
            rp = _ROBOTS_CACHE.get(base)
            if rp is None:
                rp = urllib.robotparser.RobotFileParser()
                rp.set_url(f"{base}/robots.txt")
                try:
                    rp.read()
                except Exception:  # noqa: BLE001 - robots unreachable => allow
                    _ROBOTS_CACHE[base] = _AllowAll()
                    return True
                _ROBOTS_CACHE[base] = rp
        return rp.can_fetch(user_agent, url)
    except Exception:  # noqa: BLE001
        return True


class _AllowAll(urllib.robotparser.RobotFileParser):
    def can_fetch(self, useragent, url):  # noqa: D102, ARG002
        return True
