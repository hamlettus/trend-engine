"""Learn topic-scoring weights from the engine's own results (ridge regression).

We regress a post's settled engagement on the topic features that were true when
it was drafted (frequency, growth, engagement). The fitted, non-negative,
sum-to-one coefficients are stored as LearnedWeights and blended over the
config defaults in analysis — so ranking drifts toward what actually works.

Kept deliberately simple and bounded (closed-form weighted ridge, numpy only):
interpretable, no runaway, and it only acts once it has enough samples.
"""
from __future__ import annotations

import datetime as dt

import numpy as np

from trendengine.config import Config
from trendengine.db.database import session_scope
from trendengine.db.models import (STATUS_POSTED, STATUS_SHADOW, Draft,
                                   LearnedWeight, PostMetric)
from trendengine.logging_setup import get_logger

log = get_logger(__name__)

FEATURES = ["frequency", "growth", "engagement"]


class WeightLearner:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.learn_cfg = config.raw.get("learning", {})
        self.min_samples = int(self.learn_cfg.get("min_samples_to_learn", 8))
        self.decay_days = float(self.learn_cfg.get("weight_decay_days", 45))
        self.lam = float(self.learn_cfg.get("ridge_lambda", 1.0))
        self.reward_metric = self.learn_cfg.get("reward_metric", "engagement_rate")

    def _training_rows(self, session):
        """(features vector, reward, age_days) for posts with settled metrics."""
        rows = []
        drafts = (session.query(Draft)
                  .filter(Draft.status.in_([STATUS_POSTED, STATUS_SHADOW]),
                          Draft.features.isnot(None)).all())
        for d in drafts:
            metric = (session.query(PostMetric)
                      .filter_by(draft_id=d.id)
                      .order_by(PostMetric.fetched_at.desc()).first())
            if metric is None:
                continue
            reward = self._reward(metric)
            feats = [float(d.features.get(f, 0.0)) for f in FEATURES]
            age = (dt.datetime.now(dt.timezone.utc)
                   - (d.posted_at or d.created_at).replace(tzinfo=dt.timezone.utc)
                   ).total_seconds() / 86400.0
            rows.append((feats, reward, max(0.0, age)))
        return rows

    def _reward(self, metric: PostMetric) -> float:
        if self.reward_metric == "views":
            return float(metric.views)
        if self.reward_metric == "likes":
            return float(metric.likes)
        return float(metric.engagement_rate or metric.compute_engagement_rate())

    def learn(self) -> dict[str, float] | None:
        """Fit and persist learned weights. Returns them, or None if too few samples."""
        if not self.learn_cfg.get("enabled", True):
            return None
        with session_scope() as session:
            rows = self._training_rows(session)
            if len(rows) < self.min_samples:
                log.info("WeightLearner: %d/%d samples — holding.",
                         len(rows), self.min_samples)
                return None

            X = np.array([r[0] for r in rows], dtype=float)
            y = np.array([r[1] for r in rows], dtype=float)
            ages = np.array([r[2] for r in rows], dtype=float)
            sample_w = 0.5 ** (ages / self.decay_days)   # time-decay

            # Standardise features so coefficients are comparable.
            mu, sigma = X.mean(axis=0), X.std(axis=0)
            sigma[sigma < 1e-9] = 1.0
            Xs = (X - mu) / sigma

            # Weighted ridge: w = (XᵀWX + λI)⁻¹ XᵀW y
            W = np.diag(sample_w)
            k = Xs.shape[1]
            A = Xs.T @ W @ Xs + self.lam * np.eye(k)
            b = Xs.T @ W @ y
            try:
                coef = np.linalg.solve(A, b)
            except np.linalg.LinAlgError:
                coef = np.linalg.lstsq(A, b, rcond=None)[0]

            # Map coefficients -> bounded, non-negative, sum-to-one weights.
            pos = np.clip(coef, 0.0, None)
            if pos.sum() < 1e-9:
                weights = np.ones(k) / k        # no positive signal -> uniform
            else:
                weights = pos / pos.sum()

            learned = {f: round(float(w), 4) for f, w in zip(FEATURES, weights)}
            for f, w in learned.items():
                row = session.query(LearnedWeight).filter_by(feature=f).first()
                if row is None:
                    row = LearnedWeight(feature=f)
                    session.add(row)
                row.weight = w
                row.samples = len(rows)
        log.info("WeightLearner updated from %d posts: %s", len(rows), learned)
        return learned

    @staticmethod
    def load(session) -> tuple[dict[str, float], int]:
        """Return (learned weights, sample count) or ({}, 0) if none yet."""
        rows = session.query(LearnedWeight).all()
        if not rows:
            return {}, 0
        return {r.feature: r.weight for r in rows}, max(r.samples for r in rows)
