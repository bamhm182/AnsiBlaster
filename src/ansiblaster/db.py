"""SQLAlchemy engine/session setup shared by the rest of the app.

Models live in models.py and import `Base` from here; nothing outside of app startup
(app.py) should need to touch the engine or session factory directly other than through
`session_scope`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


def make_engine(database_path: str) -> Engine:
    """Create the SQLAlchemy engine for the configured SQLite database path.

    Unlike ansible.artifacts_path (created lazily, per-job, by jobs.py), database.path has no
    other code path that ever creates its directory -- and SQLite itself won't create a
    missing parent directory, it just fails to open the file. So a fresh install pointed at
    e.g. /opt/ansiblaster/ansiblaster.db, with nothing having created /opt/ansiblaster/ yet
    (the Docker image's VOLUME declares it, but a bare `uv run` checkout has no such
    guarantee), would fail at startup. Create it here, once, up front -- the same "just make
    sure the target exists" precedent as jobs.py's own mkdir(parents=True, exist_ok=True).
    """
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{database_path}", future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory bound to the given engine."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create all tables that don't already exist."""
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a transactional session: commits on success, rolls back on error."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
