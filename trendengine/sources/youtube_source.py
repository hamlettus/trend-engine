"""YouTube trend source via the YouTube Data API v3 (free tier)."""
from __future__ import annotations

import datetime as dt

from trendengine.config import Config
from trendengine.sources.base import MissingCredentials, Source, TrendItem


class YouTubeSource(Source):
    name = "youtube"

    def fetch(self, keywords: list[str]) -> list[TrendItem]:
        api_key = Config.env("YOUTUBE_API_KEY")
        # TODO(user): free key from https://console.cloud.google.com (enable
        # "YouTube Data API v3"). Free tier is 10,000 units/day.
        if not api_key:
            raise MissingCredentials("YOUTUBE_API_KEY not set in .env")

        from googleapiclient.discovery import build

        youtube = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
        max_results = int(self.settings.get("max_results", 25))
        order = self.settings.get("order", "viewCount")
        region = self.settings.get("region_code", "US")
        within_days = int(self.settings.get("published_within_days", 7))
        published_after = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=within_days)
        ).isoformat()

        # Spread the per-run quota across keywords.
        per_kw = max(1, max_results // max(1, len(keywords)))
        items: list[TrendItem] = []

        for kw in keywords:
            search = youtube.search().list(
                q=kw, part="id", type="video", order=order,
                maxResults=min(per_kw, 50), regionCode=region,
                publishedAfter=published_after,
            ).execute()
            video_ids = [it["id"]["videoId"] for it in search.get("items", [])
                        if it.get("id", {}).get("videoId")]
            if not video_ids:
                continue

            stats = youtube.videos().list(
                part="snippet,statistics", id=",".join(video_ids)
            ).execute()
            for video in stats.get("items", []):
                snip = video.get("snippet", {})
                st = video.get("statistics", {})
                views = int(st.get("viewCount", 0))
                items.append(TrendItem(
                    source=self.name,
                    external_id=video["id"],
                    title=snip.get("title", ""),
                    url=f"https://www.youtube.com/watch?v={video['id']}",
                    score=float(views),
                    created_at=_parse_iso(snip.get("publishedAt")),
                    keyword=kw,
                    engagement={
                        "views": views,
                        "likes": int(st.get("likeCount", 0)),
                        "comments": int(st.get("commentCount", 0)),
                    },
                    extra={"channel": snip.get("channelTitle", "")},
                ))
        return items


def _parse_iso(value: str | None) -> dt.datetime:
    if not value:
        return dt.datetime.now(dt.timezone.utc)
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return dt.datetime.now(dt.timezone.utc)
