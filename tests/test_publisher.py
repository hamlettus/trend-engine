from trendengine.db.database import session_scope
from trendengine.db.models import STATUS_APPROVED, Draft
from trendengine.publishers import get_publisher
from trendengine.publishers.assisted import AssistedPublisher


def test_assisted_publisher_writes_export(config):
    with session_scope() as s:
        d = Draft(topic="ai agents", platform="instagram",
                  caption="Hello world", hashtags="#ai #agents",
                  status=STATUS_APPROVED, llm_provider="fake", llm_model="fake-1")
        s.add(d)
        s.flush()
        draft_id = d.id
        result = AssistedPublisher(config).prepare(d)

    assert result.ok
    assert result.export_path
    from pathlib import Path
    text = Path(result.export_path).read_text(encoding="utf-8")
    assert "Hello world" in text
    assert "#ai #agents" in text


def test_default_publisher_is_assisted(config):
    assert get_publisher(config).name == "assisted"


def test_stub_publishers_do_not_auto_publish(config):
    import pytest
    from trendengine.db.models import Draft
    pub = get_publisher(config, "meta_graph")
    with session_scope() as s:
        d = Draft(topic="t", caption="c")
        s.add(d); s.flush()
        with pytest.raises(NotImplementedError):
            pub.publish(d)
