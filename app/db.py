"""SQLAlchemy database setup. Models live in app/models.py."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import SETTINGS


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


# `check_same_thread=False` is required for SQLite in a multithreaded server.
# For Postgres in production, the connect_args dict is ignored.
_connect_args = (
    {"check_same_thread": False}
    if SETTINGS.database_url.startswith("sqlite")
    else {}
)
ENGINE = create_engine(
    SETTINGS.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency — yields a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Iterator[Session]:
    """For background jobs and CLI scripts."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_all() -> None:
    """Create all tables. For dev / first-boot only — use Alembic for prod migrations."""
    # Import models so SQLAlchemy registers them on Base.metadata
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=ENGINE)
