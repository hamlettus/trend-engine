import datetime as dt

from trendengine.db.database import session_scope
from trendengine.db.models import ReferenceContent
from trendengine.learning.title_model import TitleModel


def _ref(session, title, engagement):
    session.add(ReferenceContent(
        platform="youtube", external_id=f"{title[:12]}-{engagement}",
        title=title, url="https://y/x", engagement=engagement,
        publish_hour=12, hashtag_count=title.count("#"),
        style="", keyword="AI agents", collected_at=dt.datetime.now(dt.timezone.utc)))


def test_title_model_holds_below_min_samples(config):
    config.raw["learning"]["min_samples_to_learn"] = 8
    with session_scope() as s:
        _ref(s, "Why AI agents win", 100)
    assert TitleModel(config).fit() is None


def test_title_model_learns_number_signal(config):
    """Engagement is driven by titles containing a number -> has_number should
    get the strongest positive coefficient, and a hint should be emitted."""
    config.raw["learning"]["min_samples_to_learn"] = 6
    with session_scope() as s:
        # Titles WITH a number perform far better than those without.
        for i in range(6):
            _ref(s, f"{i+3} AI agent tricks that work", 5000 + i * 100)
        for i in range(6):
            _ref(s, "AI agents are useful for teams", 50 + i)

    fitted = TitleModel(config).fit()
    assert fitted is not None
    assert fitted["has_number"] == max(fitted.values())  # strongest signal
    assert fitted["has_number"] > 0

    hints = TitleModel(config).hints()
    assert any("number" in h.lower() for h in hints)


def test_title_hints_flow_into_prompt(config):
    from trendengine.analysis.aggregator import TopicScore
    from trendengine.generation.prompts import build_draft_prompt
    from tests.conftest import make_item

    topic = TopicScore(topic="ai agents", score=0.9, frequency=3, growth=0.4,
                       engagement=500, performance_weight=1.0, items=[make_item()])
    prompt = build_draft_prompt(topic, config,
                                virality_hints=["Include a specific number or statistic."])
    assert "WHAT WORKS IN THIS NICHE" in prompt
    assert "Include a specific number" in prompt


def test_drafter_injects_hints(config, monkeypatch):
    """Drafter.compose should pull title hints and put them in the prompt."""
    from trendengine.analysis.aggregator import TopicScore
    from trendengine.generation.drafter import Drafter
    from tests.conftest import make_item
    from tests.test_drafter import FakeLLM

    monkeypatch.setattr(
        "trendengine.learning.title_model.TitleModel.hints",
        lambda self, max_hints=3: ["Open with a question — questions perform well here."])

    seen = {}
    llm = FakeLLM(config, '{"caption": "Ready? Here is why AI agents matter.", '
                          '"hashtags": ["#ai"], "rationale": "x"}')
    orig = llm.generate
    def spy(prompt, system=None, temperature=None):
        seen["prompt"] = prompt
        return orig(prompt, system, temperature)
    monkeypatch.setattr(llm, "generate", spy)

    topic = TopicScore(topic="ai agents", score=0.9, frequency=3, growth=0.4,
                       engagement=500, performance_weight=1.0, items=[make_item()])
    Drafter(config, llm).compose(topic)
    assert "questions perform well" in seen["prompt"]
