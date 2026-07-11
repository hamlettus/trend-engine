"""Trend aggregation and scoring with pandas.

Turns a flat list of TrendItems into a ranked list of *topics*, each scored on:
  * frequency  — how many items reference the topic (breadth of chatter)
  * growth     — current score vs. this topic's recent historical average
  * engagement — normalised raw engagement (upvotes / views / interest)

The three are min-max normalised to 0..1, blended by the weights in config,
then nudged by a performance-feedback multiplier so topics resembling your
past winners rank higher over time.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from trendengine.config import Config
from trendengine.db.database import session_scope
from trendengine.db.models import PerformanceFeedback, TrendObservation
from trendengine.logging_setup import get_logger
from trendengine.sources.base import TrendItem
from trendengine.utils.hashing import normalize_text

log = get_logger(__name__)


@dataclass
class TopicScore:
    topic: str
    score: float
    frequency: int
    growth: float
    engagement: float
    performance_weight: float
    items: list[TrendItem] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def top_items(self, n: int = 5) -> list[TrendItem]:
        return sorted(self.items, key=lambda i: i.score, reverse=True)[:n]


def _topic_key(item: TrendItem) -> str:
    """Group items into a topic. Prefer the matched niche keyword; else fall
    back to a normalised version of the title's leading words."""
    if item.keyword:
        return item.keyword.lower()
    words = normalize_text(item.title).split()
    return " ".join(words[:4]) if words else "misc"


def _minmax(series: pd.Series) -> pd.Series:
    lo, hi = series.min(), series.max()
    if hi - lo < 1e-9:
        return pd.Series([0.5] * len(series), index=series.index)
    return (series - lo) / (hi - lo)


class TrendAnalyzer:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.weights = config.analysis.get(
            "weights", {"frequency": 0.3, "growth": 0.3, "engagement": 0.4})
        self.history_days = int(config.analysis.get("history_window_days", 7))
        self.learning_rate = float(config.analysis.get("performance_learning_rate", 0.3))

    # -- historical growth --------------------------------------------------
    def _historical_avg(self, session) -> dict[str, float]:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=self.history_days)
        rows = (session.query(TrendObservation)
                .filter(TrendObservation.observed_at >= cutoff).all())
        by_topic: dict[str, list[float]] = {}
        for r in rows:
            by_topic.setdefault(r.topic, []).append(r.score)
        return {t: (sum(v) / len(v)) for t, v in by_topic.items() if v}

    # -- learned scoring weights -------------------------------------------
    def _effective_weights(self, session) -> dict[str, float]:
        """Blend config weights with weights learned from real performance.

        Confidence rises with sample count, so early on we trust the config and
        gradually hand over to what the data says works.
        """
        from trendengine.learning.weights import WeightLearner
        learned, samples = WeightLearner.load(session)
        base = dict(self.weights)
        if not learned or samples <= 0:
            return base
        min_s = int(self.config.raw.get("learning", {}).get("min_samples_to_learn", 8))
        conf = min(1.0, samples / (2 * min_s))
        eff = {}
        for f in ("frequency", "growth", "engagement"):
            c = float(base.get(f, 0.0))
            l = float(learned.get(f, c))
            eff[f] = (1 - conf) * c + conf * l
        total = sum(eff.values()) or 1.0
        blended = {k: v / total for k, v in eff.items()}
        log.info("Effective weights (conf=%.2f, n=%d): %s",
                 conf, samples, {k: round(v, 3) for k, v in blended.items()})
        return blended

    # -- performance learning ----------------------------------------------
    def _performance_weights(self, session) -> dict[str, float]:
        """Map topic -> multiplier (>1 boost, <1 damp) from logged engagement.

        Topics whose past posts beat the average engagement rate get boosted by
        up to ``learning_rate``; underperformers get damped by up to the same.
        """
        rows = session.query(PerformanceFeedback).all()
        if not rows:
            return {}
        df = pd.DataFrame([{
            "topic": (r.topic or "").lower(),
            "er": r.engagement_rate or r.compute_engagement_rate(),
        } for r in rows if r.topic])
        if df.empty:
            return {}
        mean_er = df["er"].mean()
        if mean_er <= 0:
            return {}
        weights: dict[str, float] = {}
        for topic, grp in df.groupby("topic"):
            rel = (grp["er"].mean() - mean_er) / mean_er  # relative performance
            rel = max(-1.0, min(1.0, rel))
            weights[topic] = 1.0 + self.learning_rate * rel
        return weights

    # -- main ---------------------------------------------------------------
    def analyze(self, items: list[TrendItem]) -> list[TopicScore]:
        if not items:
            return []

        df = pd.DataFrame([{
            "topic": _topic_key(it),
            "source": it.source,
            "score": float(it.score),
            "item": it,
        } for it in items])

        with session_scope() as session:
            hist_avg = self._historical_avg(session)
            perf_weights = self._performance_weights(session)

            grouped = df.groupby("topic")
            agg = grouped.agg(
                frequency=("score", "size"),
                engagement=("score", "mean"),
                max_score=("score", "max"),
            ).reset_index()

            # Growth = current mean vs historical average (first appearance => neutral).
            def growth_for(row) -> float:
                base = hist_avg.get(row["topic"])
                cur = row["engagement"]
                if base and base > 0:
                    return (cur - base) / base
                return 0.0
            agg["growth"] = agg.apply(growth_for, axis=1)

            # Normalise each component to 0..1.
            agg["n_freq"] = _minmax(agg["frequency"].astype(float))
            agg["n_growth"] = _minmax(agg["growth"])
            agg["n_engagement"] = _minmax(agg["engagement"])

            w = self._effective_weights(session)
            agg["base_score"] = (
                w.get("frequency", 0.3) * agg["n_freq"]
                + w.get("growth", 0.3) * agg["n_growth"]
                + w.get("engagement", 0.4) * agg["n_engagement"]
            )
            agg["perf_weight"] = agg["topic"].map(
                lambda t: perf_weights.get(t, 1.0))
            agg["final_score"] = agg["base_score"] * agg["perf_weight"]

            # Persist this run's observations for future growth calc.
            for _, row in agg.iterrows():
                session.add(TrendObservation(
                    topic=row["topic"],
                    score=float(row["engagement"]),
                    frequency=int(row["frequency"]),
                ))

            agg = agg.sort_values("final_score", ascending=False)

            results: list[TopicScore] = []
            for _, row in agg.iterrows():
                topic = row["topic"]
                topic_items = [r.item for r in df[df["topic"] == topic].itertuples()]
                results.append(TopicScore(
                    topic=topic,
                    score=round(float(row["final_score"]), 4),
                    frequency=int(row["frequency"]),
                    growth=round(float(row["growth"]), 4),
                    engagement=round(float(row["engagement"]), 2),
                    performance_weight=round(float(row["perf_weight"]), 3),
                    items=topic_items,
                    sources=sorted({i.source for i in topic_items}),
                ))
        log.info("Analysed %d items into %d topics", len(items), len(results))
        return results
