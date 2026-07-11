from trendengine.config import Config


def test_config_loads_sections():
    cfg = Config.load()
    assert cfg.niche.get("name")
    assert isinstance(cfg.keywords, list) and cfg.keywords
    assert "reddit" in cfg.sources
    assert cfg.llm.get("provider") in {"ollama", "anthropic"}


def test_sources_registered():
    from trendengine.sources import SOURCE_REGISTRY
    assert {"reddit", "google_trends", "youtube", "rss"} <= set(SOURCE_REGISTRY)
