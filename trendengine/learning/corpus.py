"""Observational bootstrap: learn from public winners already out there.

Removes the cold-start. Instead of waiting for the engine's own posts to
accumulate, we mine top-performing public content in the niche (YouTube
top-by-views, high-upvote Reddit posts — all via the free read-only APIs, no
OAuth), map each winner onto the bandit's arm space (caption style, hashtag
count, post hour), and fold that evidence — weighted by how well each piece
performed — into the bandit's Beta priors.

Result: from post #1 the engine already leans toward what wins in the niche,
then its own reinforcement loop refines from there.
"""
from __future__ import annotations

import numpy as np

from trendengine.config import Config
from trendengine.db.database import session_scope
from trendengine.db.models import BanditArm, ReferenceContent, SystemState
from trendengine.learning.features import derive_arms
from trendengine.logging_setup import get_logger
from trendengine.sources import build_sources
from trendengine.sources.base import TrendItem

log = get_logger(__name__)

_BOOTSTRAP_KEY = "bandit_bootstrapped"


def _percentiles(values: list[float]) -> list[float]:
    """Rank each value to a 0..1 percentile (ties share the average rank)."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    order = np.argsort(values)
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(n, dtype=float)
    return list(ranks / (n - 1))


class CorpusLearner:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.arms_spec = config.raw.get("learning", {}).get("bandit_arms", {})

    # -- collect -----------------------------------------------------------
    def collect_reference(self, items: list[TrendItem] | None = None) -> int:
        """Pull public content (or use injected items) into ReferenceContent."""
        if items is None:
            items = []
            for source in build_sources(self.config):
                items.extend(source.collect(self.config.keywords))
        stored = 0
        with session_scope() as s:
            for it in items:
                eng = self._engagement(it)
                if eng <= 0:
                    continue
                exists = (s.query(ReferenceContent.id)
                          .filter_by(platform=it.source, external_id=str(it.external_id))
                          .first())
                if exists:
                    continue
                hashtags_text = it.extra.get("summary", "") if it.extra else ""
                from trendengine.learning.features import classify_style, count_hashtags
                s.add(ReferenceContent(
                    platform=it.source, external_id=str(it.external_id),
                    title=it.title[:1000], url=it.url, engagement=eng,
                    publish_hour=it.created_at.hour,
                    hashtag_count=count_hashtags(f"{it.title} {hashtags_text}"),
                    style=classify_style(it.title), keyword=it.keyword))
                stored += 1
        log.info("Reference corpus: +%d items", stored)
        return stored

    @staticmethod
    def _engagement(it: TrendItem) -> float:
        eng = it.engagement or {}
        for k in ("views", "upvotes", "interest"):
            if eng.get(k):
                return float(eng[k])
        return float(it.score or 0.0)

    # -- bootstrap ---------------------------------------------------------
    def bootstrap_bandit(self, force: bool = False, strength: float = 30.0) -> dict:
        """Seed bandit Beta priors from the reference corpus, weighted by
        each item's performance percentile. Idempotent unless force=True."""
        with session_scope() as s:
            done = s.get(SystemState, _BOOTSTRAP_KEY)
            if done and not force:
                return {"bootstrapped": False,
                        "note": "already bootstrapped (use --force to redo)"}

            refs = s.query(ReferenceContent).all()
            if not refs:
                return {"bootstrapped": False, "note": "no reference content — "
                        "run collect first (needs a YouTube key or Reddit creds)"}

            pcts = _percentiles([r.engagement for r in refs])

            # Reset the seeded dimensions to a uniform prior, then add evidence.
            for dim in self.arms_spec:
                for arm in s.query(BanditArm).filter_by(dimension=dim).all():
                    arm.alpha, arm.beta = 1.0, 1.0

            per_item = strength / max(1, len(refs))
            seeded = 0
            for ref, pct in zip(refs, pcts):
                arms = derive_arms(ref.title, "", ref.publish_hour, self.arms_spec)
                arms["hashtag_count"] = _nearest_str(ref.hashtag_count,
                                                     self.arms_spec.get("hashtag_count", []))
                for dim, value in arms.items():
                    arm = self._get_arm(s, dim, value)
                    arm.alpha += per_item * pct
                    arm.beta += per_item * (1.0 - pct)
                    seeded += 1

            state = done or SystemState(key=_BOOTSTRAP_KEY)
            state.value = f"{len(refs)} refs"
            s.add(state)
        log.info("Bandit warm-started from %d public winners (%d arm updates).",
                 len(refs), seeded)
        return {"bootstrapped": True, "reference_items": len(refs),
                "arm_updates": seeded}

    def _get_arm(self, session, dimension: str, value: str) -> BanditArm:
        arm = (session.query(BanditArm)
               .filter_by(dimension=dimension, value=str(value)).first())
        if arm is None:
            arm = BanditArm(dimension=dimension, value=str(value))
            session.add(arm)
            session.flush()
        return arm

    # -- report ------------------------------------------------------------
    def report(self) -> dict:
        """What the public winners look like (mean performance percentile per
        arm value) — the evidence behind the warm start."""
        with session_scope() as s:
            refs = s.query(ReferenceContent).all()
            if not refs:
                return {"reference_items": 0}
            pcts = dict(zip([r.id for r in refs],
                            _percentiles([r.engagement for r in refs])))
            by_style: dict[str, list[float]] = {}
            for r in refs:
                by_style.setdefault(r.style, []).append(pcts[r.id])
            styles = {k: round(float(np.mean(v)), 3) for k, v in by_style.items()}
        return {"reference_items": len(refs),
                "style_strength": dict(sorted(styles.items(),
                                              key=lambda kv: kv[1], reverse=True))}


def _nearest_str(value, options) -> str:
    if not options:
        return str(value)
    return str(min(options, key=lambda o: abs(float(o) - float(value))))
