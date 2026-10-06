"""SQLAlchemy engine and session handling shared by the API, the engine and scripts."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, scoped_session, sessionmaker


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
SessionLocal = scoped_session(sessionmaker(expire_on_commit=False))


def init_db(database_url: str) -> Engine:
    global _engine
    kwargs: dict = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in database_url:
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
    _engine = create_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _sqlite_fk(dbapi_conn, _):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    SessionLocal.remove()
    SessionLocal.configure(bind=_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database not initialised; call init_db() first")
    return _engine


def create_all() -> None:
    from app import models  # noqa: F401  (register models)

    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session for background work (engine, scripts). Commits on success."""
    session = sessionmaker(bind=get_engine(), expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
