"""Title virality model — learn which title features correlate with engagement.

Fits a bounded ridge regression of performance (engagement percentile) on
transferable title features (length, number, question, hashtag count) over the
public reference corpus AND your own posted results. The strongest signals are
turned into plain-English hints that are injected into the draft prompt, so the
LLM writes titles shaped like what actually performs in your niche.

Interpretable and bounded by construction: standardized features, ridge
regularisation, and a minimum sample count before any hint is emitted.
"""
from __future__ import annotations

import numpy as np

from trendengine.config import Config
from trendengine.db.database import session_scope
from trendengine.db.models import (STATUS_POSTED, Draft, PostMetric,
                                   ReferenceContent, TitleSignal)
from trendengine.learning.features import content_features, percentiles
from trendengine.logging_setup import get_logger

log = get_logger(__name__)

FEATURES = ["word_count", "has_number", "has_question", "hashtag_count"]
_HINT_THRESHOLD = 0.04   # min |standardized coef| to bother mentioning


class TitleModel:
    def __init__(self, config: Config) -> None:
        self.config = config
        learn = config.raw.get("learning", {})
        self.min_samples = int(learn.get("min_samples_to_learn", 8))
        self.lam = float(learn.get("ridge_lambda", 1.0))

    # -- training data: corpus winners + our own posted results ------------
    def _rows(self, session) -> list[tuple[list[float], float]]:
        rows: list[tuple[dict, float]] = []
        for r in session.query(ReferenceContent).all():
            feats = content_features(r.title)
            feats["hashtag_count"] = r.hashtag_count
            rows.append((feats, r.engagement))
        # Own posts (title = first caption line, engagement = latest views).
        for d in (session.query(Draft)
                  .filter(Draft.status == STATUS_POSTED).all()):
            m = (session.query(PostMetric).filter_by(draft_id=d.id)
                 .order_by(PostMetric.fetched_at.desc()).first())
            if m is None:
                continue
            title = (d.caption or d.topic).splitlines()[0]
            feats = content_features(title, d.hashtags or "")
            rows.append((feats, float(m.views or m.engagement_rate)))
        if not rows:
            return []
        y = percentiles([e for _, e in rows])
        return [([f[k] for k in FEATURES], p) for (f, _), p in zip(rows, y)]

    def fit(self) -> dict | None:
        with session_scope() as session:
            data = self._rows(session)
            if len(data) < self.min_samples:
                log.info("TitleModel: %d/%d samples — holding.",
                         len(data), self.min_samples)
                return None
            X = np.array([d[0] for d in data], dtype=float)
            y = np.array([d[1] for d in data], dtype=float)
            mu, sigma = X.mean(axis=0), X.std(axis=0)
            sigma[sigma < 1e-9] = 1.0
            Xs = (X - mu) / sigma
            k = Xs.shape[1]
            coef = np.linalg.lstsq(Xs.T @ Xs + self.lam * np.eye(k),
                                   Xs.T @ y, rcond=None)[0]
            learned = {f: round(float(c), 4) for f, c in zip(FEATURES, coef)}
            for f, c in learned.items():
                row = session.get(TitleSignal, f) or TitleSignal(feature=f)
                row.coef, row.samples = c, len(data)
                session.add(row)
        log.info("TitleModel fit on %d rows: %s", len(data), learned)
        return learned

    # -- turn coefficients into prompt hints -------------------------------
    def hints(self, max_hints: int = 3) -> list[str]:
        with session_scope() as session:
            signals = {s.feature: s.coef for s in session.query(TitleSignal).all()}
        if not signals:
            return []
        ranked = sorted(signals.items(), key=lambda kv: abs(kv[1]), reverse=True)
        out: list[str] = []
        for feat, coef in ranked:
            if abs(coef) < _HINT_THRESHOLD:
                continue
            msg = _HINT_MESSAGES.get((feat, coef > 0))
            if msg:
                out.append(msg)
            if len(out) >= max_hints:
                break
        return out

    def report(self) -> dict:
        with session_scope() as session:
            return {s.feature: s.coef for s in session.query(TitleSignal).all()}


_HINT_MESSAGES = {
    ("has_number", True): "Include a specific number or statistic — numbers correlate with higher engagement here.",
    ("has_number", False): "Avoid leading with numbers; they underperform in this niche.",
    ("has_question", True): "Open with a question — questions perform well in this niche.",
    ("has_question", False): "Prefer a statement over a question for the hook.",
    ("word_count", True): "Use a longer, more descriptive title (more words tend to win here).",
    ("word_count", False): "Keep the title short and punchy (shorter titles win here).",
    ("hashtag_count", True): "Use a few more hashtags — higher hashtag counts perform better here.",
    ("hashtag_count", False): "Use fewer hashtags — lighter hashtag use performs better here.",
}
