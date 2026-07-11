"""Dashboard security (basic auth) + the phone-triggerable campaigns page."""
import base64
import warnings

from starlette.testclient import TestClient

from trendengine.config import Config
from trendengine.db import database
from trendengine.db.database import init_db


def _client(tmp_path):
    cfg = Config.load()
    database._engine = None
    database._SessionLocal = None
    database.init_engine(cfg, db_path=tmp_path / "d.sqlite3")
    init_db(cfg)
    from trendengine.dashboard.app import create_app
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return cfg, TestClient(create_app(cfg))


def _teardown():
    database._engine = None
    database._SessionLocal = None


def test_no_auth_when_password_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    _cfg, c = _client(tmp_path)
    try:
        assert c.get("/").status_code == 200            # open in dev
    finally:
        _teardown()


def test_basic_auth_enforced_when_password_set(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "s3cret")
    _cfg, c = _client(tmp_path)
    try:
        # No credentials -> challenged.
        r = c.get("/")
        assert r.status_code == 401
        assert "WWW-Authenticate" in r.headers

        # Wrong credentials -> rejected.
        bad = base64.b64encode(b"admin:nope").decode()
        assert c.get("/", headers={"Authorization": f"Basic {bad}"}).status_code == 401

        # Correct credentials -> allowed.
        good = base64.b64encode(b"admin:s3cret").decode()
        assert c.get("/", headers={"Authorization": f"Basic {good}"}).status_code == 200
    finally:
        _teardown()


def test_campaigns_page_lists_and_marks_authorization(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    _cfg, c = _client(tmp_path)
    try:
        r = c.get("/campaigns")
        assert r.status_code == 200
        assert "Clipping campaigns" in r.text
        # The shipped example is unauthorized -> shown as blocked, no run button.
        assert "not authorized" in r.text
        assert 'href="/campaigns"' in r.text          # nav link present
    finally:
        _teardown()


def test_campaign_run_route_redirects(tmp_path, monkeypatch):
    """Triggering a run returns a redirect (job runs in a background thread)."""
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    _cfg, c = _client(tmp_path)
    try:
        r = c.post("/campaigns/example-campaign/run", data={"live": ""},
                   follow_redirects=False)
        assert r.status_code == 303
    finally:
        _teardown()
