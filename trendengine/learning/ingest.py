"""Close the loop: pull settled performance and reward the learners.

For each live post, fetch current stats from the platform, store a time-series
snapshot, and — once engagement has had time to settle — fold the outcome into
the bandit and re-fit the weight learner. All automatic; no manual logging.

The stats fetcher is injectable so this is testable offline and swappable per
platform (default: the YouTube publisher's stats endpoint).
"""
from __future__ import annotations

import datetime as dt
from typing import Callable

from trendengine.config import Config
from trendengine.db.database import session_scope
from trendengine.db.models import STATUS_POSTED, Draft, PostMetric
from trendengine.learning.bandit import ThompsonBandit
from trendengine.learning.weights import WeightLearner
from trendengine.logging_setup import get_logger

log = get_logger(__name__)

# stats_fetcher(video_id) -> {"views": int, "likes": int, "comments": int} | None
StatsFetcher = Callable[[str], dict | None]


class PerformanceIngestor:
    def __init__(self, config: Config, stats_fetcher: StatsFetcher | None = None) -> None:
        self.config = config
        self.learn_cfg = config.raw.get("learning", {})
        windows = self.learn_cfg.get("ingest_after_hours", [6, 24, 72])
        self.settle_hours = max(windows) if windows else 24
        self._fetcher = stats_fetcher

    def _default_fetcher(self) -> StatsFetcher:
        from trendengine.publishers import get_publisher
        pub = get_publisher(self.config, "youtube")
        return pub.fetch_stats  # type: ignore[attr-defined]

    def run(self) -> dict:
        if not self.learn_cfg.get("enabled", True):
            return {"ingested": 0, "rewarded": 0}
        fetcher = self._fetcher or self._default_fetcher()
        bandit = ThompsonBandit(self.config)
        ingested = rewarded = 0

        with session_scope() as session:
            posts = (session.query(Draft)
                     .filter(Draft.status == STATUS_POSTED,
                             Draft.external_post_id.isnot(None)).all())
            to_reward: list[tuple[dict, float]] = []
            for d in posts:
                try:
                    stats = fetcher(d.external_post_id)
                except Exception as exc:  # noqa: BLE001
                    log.warning("stats fetch failed for %s: %s", d.external_post_id, exc)
                    continue
                if not stats:
                    continue
                metric = PostMetric(
                    draft_id=d.id, external_post_id=d.external_post_id,
                    views=int(stats.get("views", 0)),
                    likes=int(stats.get("likes", 0)),
                    comments=int(stats.get("comments", 0)))
                metric.engagement_rate = metric.compute_engagement_rate()
                session.add(metric)
                ingested += 1

                posted_at = (d.posted_at or d.created_at)
                age_h = (dt.datetime.now(dt.timezone.utc)
                         - posted_at.replace(tzinfo=dt.timezone.utc)).total_seconds() / 3600
                if age_h >= self.settle_hours and not d.learned_applied and d.arms:
                    to_reward.append((dict(d.arms), metric.engagement_rate))
                    d.learned_applied = True
                    rewarded += 1

        # Apply bandit rewards (own transactions) then re-fit weights.
        for arms, reward in to_reward:
            bandit.update(arms, reward)
        if rewarded:
            WeightLearner(self.config).learn()
            from trendengine.learning.title_model import TitleModel
            TitleModel(self.config).fit()  # refresh title signals with new results

        log.info("Ingest: %d metrics, %d posts rewarded.", ingested, rewarded)
        return {"ingested": ingested, "rewarded": rewarded}
