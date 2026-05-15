"""Synchronous SQLAlchemy session for Celery tasks.

The FastAPI side uses asyncpg, but Celery's prefork pool is sync —
running `asyncio.run()` per task would create a new event loop and
fresh connections every call. A dedicated sync engine keeps the
worker's connections pooled and avoids the cost.

Keep the schema definitions in `app.models` — those are async/sync
agnostic (just SQLAlchemy 2.0 declarative). Only the engine and
session factory differ here.
"""
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_settings = get_settings()

sync_engine = create_engine(
    _settings.sync_database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    future=True,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope around a series of operations."""
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
