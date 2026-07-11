"""Multi-armed bandit (Beta-Bernoulli / Thompson sampling) over post knobs.

Each controllable dimension (post_hour, caption_style, hashtag_count) is a set of
arms. For each post the engine samples one arm per dimension. When that post's
engagement settles, the arm is rewarded: success if engagement beats a running
threshold. Over time the sampler concentrates on winners while still exploring
(an epsilon floor guarantees the engine keeps trying alternatives).

Guardrails against chasing noise:
  * Beta(1,1) uniform prior — nothing is assumed good until it earns it.
  * Reward is binarised against a *running median*, so one viral fluke can't
    dominate a continuous reward scale.
  * An explicit epsilon floor keeps exploration alive indefinitely.
"""
from __future__ import annotations

import random

import numpy as np

from trendengine.config import Config
from trendengine.db.database import session_scope
from trendengine.db.models import BanditArm, PostMetric
from trendengine.logging_setup import get_logger

log = get_logger(__name__)


class ThompsonBandit:
    def __init__(self, config: Config) -> None:
        self.config = config
        learn = config.raw.get("learning", {})
        self.arms_spec: dict[str, list] = learn.get("bandit_arms", {})
        self.epsilon = float(learn.get("bandit_explore", 0.15))

    def dimensions(self) -> list[str]:
        return list(self.arms_spec.keys())

    def _get_arm(self, session, dimension: str, value: str) -> BanditArm:
        arm = (session.query(BanditArm)
               .filter_by(dimension=dimension, value=str(value)).first())
        if arm is None:
            arm = BanditArm(dimension=dimension, value=str(value))
            session.add(arm)
            session.flush()
        return arm

    def select(self) -> dict[str, str]:
        """Pick one arm per dimension via Thompson sampling (+ epsilon explore)."""
        chosen: dict[str, str] = {}
        with session_scope() as session:
            for dim, values in self.arms_spec.items():
                if not values:
                    continue
                if random.random() < self.epsilon:
                    chosen[dim] = str(random.choice(values))
                    continue
                best_val, best_sample = None, -1.0
                for v in values:
                    arm = self._get_arm(session, dim, v)
                    sample = float(np.random.beta(max(arm.alpha, 1e-3),
                                                  max(arm.beta, 1e-3)))
                    if sample > best_sample:
                        best_sample, best_val = sample, str(v)
                chosen[dim] = best_val
        return chosen

    def _running_threshold(self, session, metric: str) -> float:
        """Median engagement across settled posts — the success bar."""
        rows = [m.engagement_rate for m in session.query(PostMetric).all()
                if m.engagement_rate is not None]
        if len(rows) < 3:
            return 0.0  # early on, any nonzero engagement counts as success
        return float(np.median(rows))

    def update(self, arms: dict[str, str], reward: float,
               threshold: float | None = None) -> None:
        """Fold one post's outcome into its chosen arms."""
        if not arms:
            return
        with session_scope() as session:
            if threshold is None:
                threshold = self._running_threshold(session, "engagement_rate")
            success = 1.0 if reward > threshold else 0.0
            for dim, value in arms.items():
                arm = self._get_arm(session, dim, str(value))
                arm.alpha += success
                arm.beta += (1.0 - success)
                arm.pulls += 1
                arm.reward_sum += float(reward)
        log.info("Bandit updated: reward=%.4f threshold=%.4f success=%s arms=%s",
                 reward, threshold, reward > (threshold or 0), arms)

    def snapshot(self) -> list[dict]:
        """Human-readable arm stats for the dashboard/CLI."""
        out = []
        with session_scope() as session:
            for arm in session.query(BanditArm).order_by(
                    BanditArm.dimension, BanditArm.value).all():
                out.append({
                    "dimension": arm.dimension, "value": arm.value,
                    "pulls": arm.pulls, "mean_reward": round(arm.mean_reward, 4),
                    "win_rate": round(arm.alpha / (arm.alpha + arm.beta), 3),
                })
        return out
