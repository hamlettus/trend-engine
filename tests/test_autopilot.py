import datetime as dt

import pytest

from trendengine.llm.base import LLMClient
from trendengine.publishers.base import PublishResult
from trendengine.sources.base import TrendItem

GOOD_CAPTION = ("Local LLMs just crossed the line from toy to tool — here's the "
                "specific reason that matters for solo creators this week.")


class SmartFakeLLM(LLMClient):
    """Returns a draft OR a critique depending on which prompt it sees."""
    provider = "fake"

    def __init__(self, config, draft, critique):
        super().__init__(config)
        self._draft, self._critique = draft, critique

    @property
    def model(self):
        return "fake-1"

    def generate(self, prompt, system=None, temperature=None):
        if "verdict" in prompt or "Score it" in prompt:
            return self._critique
        return self._draft


class FakeSource:
    def __init__(self, keywords):
        self.keywords = keywords

    def collect(self, keywords):
        now = dt.datetime.now(dt.timezone.utc)
        out = []
        for kw in self.keywords:
            for i in range(3):
                out.append(TrendItem(source="reddit", external_id=f"{kw}-{i}",
                                     title=f"{kw} breakthrough {i}",
                                     url=f"https://e.com/{kw}/{i}", score=100 + i,
                                     created_at=now, keyword=kw))
        return out


def _wire(monkeypatch, config, keywords=("AI agents",),
          draft='{"caption": "%s", "hashtags": ["#agents"], "rationale": "hot"}' % GOOD_CAPTION,
          critique='{"score": 9, "issues": [], "verdict": "pass"}'):
    monkeypatch.setattr("trendengine.autopilot.build_sources",
                        lambda cfg: [FakeSource(list(keywords))])
    monkeypatch.setattr("trendengine.autopilot.get_llm",
                        lambda cfg: SmartFakeLLM(config, draft, critique))


def test_shadow_cycle_records_but_does_not_post(config, monkeypatch):
    config.raw["autopilot"].update(enabled=True, mode="shadow", publisher="youtube")
    _wire(monkeypatch, config)
    stats = __import__("trendengine.autopilot", fromlist=["run_autopilot"]).run_autopilot(config)
    assert stats.shadowed == 1 and stats.posted == 0

    from trendengine.db.database import session_scope
    from trendengine.db.models import Draft, STATUS_SHADOW
    with session_scope() as s:
        d = s.query(Draft).filter(Draft.status == STATUS_SHADOW).one()
        assert d.auto is True
        assert d.arms and "caption_style" in d.arms
        assert d.features and "engagement" in d.features
        assert d.external_post_id is None  # nothing uploaded


def test_gated_out_draft_is_rejected_not_posted(config, monkeypatch):
    config.raw["autopilot"].update(enabled=True, mode="shadow")
    _wire(monkeypatch, config,
          critique='{"score": 2, "issues": ["off-brand"], "verdict": "reject"}')
    from trendengine.autopilot import run_autopilot
    stats = run_autopilot(config)
    assert stats.gated_out >= 1 and stats.posted == 0 and stats.shadowed == 0


def test_canary_budget_caps_posts(config, monkeypatch):
    config.raw["autopilot"].update(enabled=True, mode="shadow")
    config.raw["autopilot"]["canary"]["start_per_day"] = 1
    _wire(monkeypatch, config, keywords=("AI agents", "local LLM"))  # 2 topics
    from trendengine.autopilot import run_autopilot
    stats = run_autopilot(config)
    assert stats.shadowed == 1  # capped at 1 despite 2 eligible topics


def test_live_cycle_posts_then_ingest_rewards_bandit(config, monkeypatch):
    config.raw["autopilot"].update(enabled=True, mode="live", publisher="youtube")
    config.raw["learning"]["ingest_after_hours"] = [0]  # settle immediately for the test
    _wire(monkeypatch, config)

    # Fake out rendering and the real upload.
    monkeypatch.setattr("trendengine.media.ShortGenerator.render",
                        lambda self, caption, topic, draft_id: __fake_video(config))

    class FakePub:
        name = "youtube"
        def publish(self, draft):
            return PublishResult(ok=True, message="ok", external_post_id="vid123")
    monkeypatch.setattr("trendengine.autopilot.get_publisher",
                        lambda cfg, name=None: FakePub())

    from trendengine.autopilot import run_autopilot
    stats = run_autopilot(config)
    assert stats.posted == 1, stats.summary()

    from trendengine.db.database import session_scope
    from trendengine.db.models import Draft, STATUS_POSTED
    with session_scope() as s:
        d = s.query(Draft).filter(Draft.status == STATUS_POSTED).one()
        assert d.external_post_id == "vid123"
        arms = dict(d.arms)

    # Ingest with a fake stats fetcher -> should reward the bandit + learn.
    from trendengine.learning import PerformanceIngestor
    res = PerformanceIngestor(config, stats_fetcher=lambda vid: {
        "views": 1000, "likes": 80, "comments": 20}).run()
    assert res["ingested"] == 1 and res["rewarded"] == 1

    from trendengine.learning import ThompsonBandit
    snap = {(a["dimension"], a["value"]): a for a in ThompsonBandit(config).snapshot()}
    assert snap[("caption_style", str(arms["caption_style"]))]["pulls"] == 1


def __fake_video(config):
    from pathlib import Path
    from trendengine.config import PROJECT_ROOT
    p = PROJECT_ROOT / "media_out" / "fake.mp4"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00\x00")
    return p
