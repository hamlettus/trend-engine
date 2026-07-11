"""Reddit trend source via PRAW (read-only, respects Reddit's API)."""
from __future__ import annotations

import datetime as dt

from trendengine.config import Config
from trendengine.sources.base import MissingCredentials, Source, TrendItem


class RedditSource(Source):
    name = "reddit"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self._reddit = None

    def _client(self):
        if self._reddit is not None:
            return self._reddit
        client_id = Config.env("REDDIT_CLIENT_ID")
        client_secret = Config.env("REDDIT_CLIENT_SECRET")
        user_agent = Config.env("REDDIT_USER_AGENT", "trend-engine/0.1")
        # TODO(user): create a free "script" app at https://www.reddit.com/prefs/apps
        if not client_id or not client_secret:
            raise MissingCredentials(
                "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set in .env")
        import praw  # imported lazily so the app runs without the dep until needed

        self._reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            check_for_updates=False,
        )
        self._reddit.read_only = True
        return self._reddit

    def fetch(self, keywords: list[str]) -> list[TrendItem]:
        reddit = self._client()
        subs = self.settings.get("subreddits", [])
        listing = self.settings.get("listing", "hot")
        limit = int(self.settings.get("limit", 25))
        min_score = int(self.settings.get("min_score", 0))
        time_filter = self.settings.get("time_filter", "day")
        kw_lower = [k.lower() for k in keywords]

        items: list[TrendItem] = []
        for sub_name in subs:
            subreddit = reddit.subreddit(sub_name)
            if listing == "top":
                submissions = subreddit.top(time_filter=time_filter, limit=limit)
            elif listing == "new":
                submissions = subreddit.new(limit=limit)
            elif listing == "rising":
                submissions = subreddit.rising(limit=limit)
            else:
                submissions = subreddit.hot(limit=limit)

            for post in submissions:
                if getattr(post, "stickied", False):
                    continue
                if post.score < min_score:
                    continue
                title = post.title or ""
                # Tag with the first matching niche keyword (empty if none matched).
                haystack = f"{title} {getattr(post, 'selftext', '')}".lower()
                matched = next((k for k, kl in zip(keywords, kw_lower) if kl in haystack), "")
                items.append(TrendItem(
                    source=self.name,
                    external_id=post.id,
                    title=title,
                    url=f"https://reddit.com{post.permalink}",
                    score=float(post.score),
                    created_at=dt.datetime.fromtimestamp(post.created_utc, dt.timezone.utc),
                    keyword=matched or sub_name,
                    engagement={
                        "upvotes": post.score,
                        "comments": post.num_comments,
                        "upvote_ratio": getattr(post, "upvote_ratio", None),
                    },
                    extra={"subreddit": sub_name, "over_18": post.over_18},
                ))
        return items
