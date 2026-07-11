from trendengine.analysis.aggregator import TrendAnalyzer
from tests.conftest import make_item


def test_analyze_ranks_topics(config):
    items = [
        make_item(source="reddit", title="AI agents everywhere", score=500, keyword="AI agents"),
        make_item(source="youtube", title="Building AI agents", score=9000, keyword="AI agents"),
        make_item(source="rss", title="Prompt tips", score=40, keyword="prompt engineering"),
    ]
    topics = TrendAnalyzer(config).analyze(items)
    assert topics, "expected at least one topic"
    # AI agents appears twice across two sources -> should rank first.
    assert topics[0].topic == "ai agents"
    assert topics[0].frequency == 2
    assert set(topics[0].sources) == {"reddit", "youtube"}


def test_analyze_empty_returns_empty(config):
    assert TrendAnalyzer(config).analyze([]) == []


def test_performance_feedback_reweights(config):
    """A topic with strong logged engagement gets a >1 performance weight."""
    from trendengine.db.database import session_scope
    from trendengine.db.models import PerformanceFeedback

    with session_scope() as s:
        s.add(PerformanceFeedback(topic="ai agents", platform="instagram",
                                  likes=900, reach=1000, engagement_rate=0.9))
        s.add(PerformanceFeedback(topic="prompt engineering", platform="instagram",
                                  likes=1, reach=1000, engagement_rate=0.001))

    items = [
        make_item(title="AI agents", score=100, keyword="AI agents"),
        make_item(title="Prompt engineering 101", score=100, keyword="prompt engineering"),
    ]
    topics = {t.topic: t for t in TrendAnalyzer(config).analyze(items)}
    assert topics["ai agents"].performance_weight > 1.0
    assert topics["prompt engineering"].performance_weight < 1.0
