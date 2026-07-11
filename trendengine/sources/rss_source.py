"""RSS/Atom trend source via feedparser (respects robots.txt)."""
from __future__ import annotations

import datetime as dt
import time

from trendengine.sources.base import Source, TrendItem
from trendengine.utils.ratelimit import robots_allows


class RSSSource(Source):
    name = "rss"

    def fetch(self, keywords: list[str]) -> list[TrendItem]:
        import feedparser

        feeds = self.settings.get("feeds", [])
        respect_robots = self.settings.get("respect_robots", True)
        kw_lower = [k.lower() for k in keywords]
        items: list[TrendItem] = []

        for feed_url in feeds:
            if respect_robots and not robots_allows(feed_url):
                # Politely skip feeds the host disallows.
                continue
            parsed = feedparser.parse(feed_url)
            feed_title = parsed.feed.get("title", feed_url) if parsed.feed else feed_url

            for entry in parsed.entries:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", "")
                haystack = f"{title} {summary}".lower()
                matched = next(
                    (k for k, kl in zip(keywords, kw_lower) if kl in haystack), "")
                # RSS has no engagement metric; use recency as a proxy score so
                # fresher items rank higher (analysis normalises across sources).
                published = _entry_time(entry)
                recency_score = _recency_score(published)
                items.append(TrendItem(
                    source=self.name,
                    external_id=entry.get("id", link),
                    title=title,
                    url=link,
                    score=recency_score,
                    created_at=published,
                    keyword=matched,
                    engagement={"recency_score": recency_score},
                    extra={"feed": feed_title, "summary": summary[:500]},
                ))
        return items


def _entry_time(entry) -> dt.datetime:
    for key in ("published_parsed", "updated_parsed"):
        tm = entry.get(key)
        if tm:
            return dt.datetime.fromtimestamp(time.mktime(tm), dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def _recency_score(published: dt.datetime) -> float:
    """0..100, decaying over ~7 days."""
    age_hours = (dt.datetime.now(dt.timezone.utc) - published).total_seconds() / 3600
    return round(max(0.0, 100.0 - (age_hours / (24 * 7)) * 100.0), 2)
