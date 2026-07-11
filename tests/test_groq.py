import pytest

from trendengine.llm import get_llm
from trendengine.llm.base import LLMError
from trendengine.llm.groq_client import GroqClient


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_factory_returns_groq_when_selected(config):
    config.raw["llm"]["provider"] = "groq"
    assert isinstance(get_llm(config), GroqClient)


def test_groq_requires_key(config, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMError) as e:
        GroqClient(config).generate("hi")
    assert "GROQ_API_KEY" in str(e.value)


def test_groq_generate_parses_content(config, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        return _Resp(200, {"choices": [{"message": {"content": "  hello world  "}}]})

    monkeypatch.setattr("trendengine.llm.groq_client.requests.post", fake_post)
    out = GroqClient(config).generate("draft this", system="be brief")
    assert out == "hello world"
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer gsk_test"
    roles = [m["role"] for m in captured["body"]["messages"]]
    assert roles == ["system", "user"]


def test_groq_maps_http_errors(config, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr("trendengine.llm.groq_client.requests.post",
                        lambda *a, **k: _Resp(401, text="bad key"))
    with pytest.raises(LLMError) as e:
        GroqClient(config).generate("x")
    assert "401" in str(e.value)


def test_groq_health_check_without_key(config, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    ok, detail = GroqClient(config).health_check()
    assert ok is False and "GROQ_API_KEY" in detail
