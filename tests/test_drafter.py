from trendengine.analysis.aggregator import TopicScore
from trendengine.generation.drafter import Drafter, _merge_hashtags, _parse_llm_json
from trendengine.llm.base import LLMClient
from tests.conftest import make_item


class FakeLLM(LLMClient):
    provider = "fake"

    def __init__(self, config, payload):
        super().__init__(config)
        self._payload = payload

    @property
    def model(self):
        return "fake-1"

    def generate(self, prompt, system=None, temperature=None):
        return self._payload


def test_parse_llm_json_tolerates_fences():
    raw = '```json\n{"caption": "hi", "hashtags": ["#a"], "rationale": "why"}\n```'
    data = _parse_llm_json(raw)
    assert data["caption"] == "hi"


def test_parse_llm_json_extracts_from_prose():
    raw = 'Sure! Here you go:\n{"caption": "x", "hashtags": [], "rationale": ""}\nHope that helps'
    assert _parse_llm_json(raw)["caption"] == "x"


def test_merge_hashtags_dedups_and_prefixes():
    tags = _merge_hashtags(["#AI", "productivity"], ["#ai", "#agents"])
    assert tags == ["#AI", "#productivity", "#agents"]


def test_drafter_creates_pending_draft(config):
    llm = FakeLLM(config, '{"caption": "AI agents are here", '
                          '"hashtags": ["#agents"], "rationale": "hot topic"}')
    topic = TopicScore(topic="ai agents", score=0.9, frequency=3, growth=0.5,
                       engagement=500, performance_weight=1.0,
                       items=[make_item()])
    ids = Drafter(config, llm).generate([topic])
    assert len(ids) == 1

    from trendengine.db.database import session_scope
    from trendengine.db.models import Draft, STATUS_PENDING
    with session_scope() as s:
        d = s.get(Draft, ids[0])
        assert d.status == STATUS_PENDING
        assert "AI agents" in d.caption
        assert "#agents" in d.hashtags
        assert d.llm_provider == "fake"
