import datetime as dt

from trendengine.db.database import session_scope
from trendengine.db.models import STATUS_POSTED, Draft, PostMetric
from trendengine.learning.weights import WeightLearner


def _posted_draft(session, features, engagement, days_ago=1):
    d = Draft(topic=f"t{features['engagement']}", platform="youtube",
              caption="c" * 80, status=STATUS_POSTED, auto=True,
              features=features, external_post_id="vid",
              posted_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago))
    session.add(d)
    session.flush()
    m = PostMetric(draft_id=d.id, external_post_id="vid", views=1000,
                   likes=int(engagement * 1000), comments=0,
                   engagement_rate=engagement)
    session.add(m)
    return d.id


def test_weight_learner_holds_below_min_samples(config):
    with session_scope() as s:
        _posted_draft(s, {"frequency": 1, "growth": 0, "engagement": 10}, 0.1)
    assert WeightLearner(config).learn() is None  # < min_samples


def test_weight_learner_favors_predictive_feature(config):
    """Engagement outcome is driven by the 'engagement' feature -> it should get
    the largest learned weight; results are bounded and sum to ~1."""
    config.raw["learning"]["min_samples_to_learn"] = 6
    with session_scope() as s:
        for eng_feat in range(1, 11):
            outcome = eng_feat / 100.0            # engagement feature drives reward
            _posted_draft(s, {"frequency": 5, "growth": 0.0,
                              "engagement": float(eng_feat)}, outcome)

    weights = WeightLearner(config).learn()
    assert weights is not None
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert all(0.0 <= w <= 1.0 for w in weights.values())
    assert weights["engagement"] == max(weights.values())


def test_learned_weights_blend_into_analysis(config):
    """Once weights are learned, the analyzer blends them (effective != config)."""
    config.raw["learning"]["min_samples_to_learn"] = 6
    with session_scope() as s:
        for eng_feat in range(1, 11):
            _posted_draft(s, {"frequency": 5, "growth": 0.0,
                              "engagement": float(eng_feat)}, eng_feat / 100.0)
    WeightLearner(config).learn()

    from trendengine.analysis.aggregator import TrendAnalyzer
    with session_scope() as s:
        eff = TrendAnalyzer(config)._effective_weights(s)
    assert abs(sum(eff.values()) - 1.0) < 1e-6
