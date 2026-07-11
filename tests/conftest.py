"""Shared test fixtures — an in-repo temp SQLite DB and a loaded Config."""
from __future__ import annotations

import datetime as dt

import pytest

from trendengine.config import Config
from trendengine.db import database
from trendengine.db.database import init_db
from trendengine.sources.base import TrendItem


@pytest.fixture
def config(tmp_path):
    cfg = Config.load()
    # Redirect the DB to a temp file and reset the module-level engine.
    database._engine = None
    database._SessionLocal = None
    database.init_engine(cfg, db_path=tmp_path / "test.sqlite3")
    init_db(cfg)
    yield cfg
    database._engine = None
    database._SessionLocal = None


def make_item(source="reddit", title="AI agents are booming", score=100.0,
              keyword="AI agents", url=None):
    return TrendItem(
        source=source,
        external_id=f"{source}-{title[:8]}-{score}",
        title=title,
        url=url or f"https://example.com/{abs(hash(title))}",
        score=score,
        created_at=dt.datetime.now(dt.timezone.utc),
        keyword=keyword,
    )
