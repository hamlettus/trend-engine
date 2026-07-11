"""SQLite engine + session factory."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from trendengine.config import Config
from trendengine.db.models import Base
from trendengine.logging_setup import get_logger

log = get_logger(__name__)

_engine = None
_SessionLocal: sessionmaker | None = None


def init_engine(config: Config | None = None, db_path: str | Path | None = None):
    """Create (once) the SQLite engine and session factory."""
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    if db_path is None:
        db_path = (config.db_path() if config else Path("trendengine.sqlite3"))
    _engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False},  # scheduler thread + dashboard thread
    )
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)
    return _engine


def init_db(config: Config | None = None) -> None:
    """Create all tables (idempotent)."""
    engine = init_engine(config)
    Base.metadata.create_all(engine)
    log.info("Database ready at %s", engine.url)


def get_sessionmaker() -> sessionmaker:
    if _SessionLocal is None:
        raise RuntimeError("Database not initialised — call init_db()/init_engine() first.")
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session context manager."""
    sm = get_sessionmaker()
    session = sm()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
