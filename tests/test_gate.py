from trendengine.guardrails.gate import QualityGate
from tests.test_drafter import FakeLLM


def _gate(config, critique='{"score": 9, "issues": [], "verdict": "pass"}'):
    return QualityGate(config, FakeLLM(config, critique))


def test_gate_rejects_short_caption(config):
    r = _gate(config).check(0.9, "too short", "#ai", "ai agents")
    assert not r.passed
    assert any("short" in reason for reason in r.reasons)


def test_gate_rejects_banned_term(config):
    config.raw["guardrails"]["banned_terms"] = ["crypto pump"]
    caption = "This is a totally fine length caption about a crypto pump scheme " * 2
    r = _gate(config).check(0.9, caption, "#ai", "ai agents")
    assert not r.passed
    assert any("banned" in reason for reason in r.reasons)


def test_gate_rejects_low_topic_score(config):
    caption = "A perfectly reasonable caption that is clearly long enough to pass length checks."
    r = _gate(config).check(0.1, caption, "#ai", "ai agents")
    assert not r.passed


def test_gate_rejects_on_low_self_critique(config):
    caption = "A perfectly reasonable caption that is clearly long enough to pass length checks."
    r = _gate(config, critique='{"score": 3, "issues": ["off-brand"], "verdict": "reject"}')\
        .check(0.9, caption, "#ai", "ai agents")
    assert not r.passed
    assert r.score is not None and r.score < 7


def test_gate_passes_clean_draft(config):
    caption = "A genuinely on-brand, specific caption about why local LLMs matter this week for creators."
    r = _gate(config).check(0.9, caption, "#ai #localllm", "local llm")
    assert r.passed, r.reasons
    assert r.score == 9


def test_gate_fails_closed_when_llm_errors(config):
    from trendengine.llm.base import LLMClient, LLMError

    class BrokenLLM(LLMClient):
        provider = "broken"
        @property
        def model(self): return "x"
        def generate(self, prompt, system=None, temperature=None):
            raise LLMError("down")

    caption = "A perfectly reasonable caption that is clearly long enough to pass length checks."
    r = QualityGate(config, BrokenLLM(config)).check(0.9, caption, "#ai", "novel topic")
    assert not r.passed  # fails closed — no blind auto-post
