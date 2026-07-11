import datetime as dt
import warnings

from starlette.testclient import TestClient

from trendengine.config import Config
from trendengine.db import database
from trendengine.db.database import init_db, session_scope
from trendengine.db.models import ReferenceContent
from trendengine.learning import CorpusLearner, TitleModel


def _client(tmp_path):
    cfg = Config.load()
    database._engine = None
    database._SessionLocal = None
    database.init_engine(cfg, db_path=tmp_path / "dash.sqlite3")
    init_db(cfg)
    from trendengine.dashboard.app import create_app
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return cfg, TestClient(create_app(cfg))


def test_insights_tab_renders_empty(tmp_path):
    _cfg, c = _client(tmp_path)
    try:
        r = c.get("/insights")
        assert r.status_code == 200
        assert "What the engine has learned" in r.text
        assert "Not fitted yet" in r.text            # title model empty-state
    finally:
        database._engine = None
        database._SessionLocal = None


def test_insights_tab_renders_learned_state(tmp_path):
    cfg, c = _client(tmp_path)
    try:
        cfg.raw["learning"]["min_samples_to_learn"] = 6
        with session_scope() as s:
            for i in range(6):
                s.add(ReferenceContent(platform="youtube", external_id=f"hi{i}",
                    title=f"{i+3} AI agent tricks that win", url="u",
                    engagement=8000 + i, publish_hour=17, hashtag_count=3,
                    style="listicle", keyword="AI agents"))
            for i in range(6):
                s.add(ReferenceContent(platform="youtube", external_id=f"lo{i}",
                    title="AI agents are decent", url="u", engagement=40 + i,
                    publish_hour=3, hashtag_count=0, style="bold_claim",
                    keyword="AI agents"))
        CorpusLearner(cfg).bootstrap_bandit()
        TitleModel(cfg).fit()

        r = c.get("/insights")
        assert r.status_code == 200
        # Title model coefficients + hints rendered
        assert "has_number" in r.text
        assert "Hints now steering generation" in r.text
        # Bandit arms rendered with the winning style marked best
        assert "caption_style" in r.text and "listicle" in r.text
        # KPI shows the 12 reference items
        assert ">12<" in r.text
        # nav link present
        assert 'href="/insights"' in r.text
    finally:
        database._engine = None
        database._SessionLocal = None
