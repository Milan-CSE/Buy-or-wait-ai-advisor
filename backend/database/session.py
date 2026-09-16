"""
backend/database/session.py

Engine configuration, session factory, and connection management.
Supports PostgreSQL (production) and SQLite (testing) via standard connection strings.
"""
from __future__ import annotations
import os
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# Base metadata class for all persistent entities
Base = declarative_base()

DEFAULT_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///d:/hacker_rank_projectt/buyorwait_dev.db"
)


def get_engine(db_url: str | None = None):
    url = db_url or DEFAULT_DATABASE_URL
    is_sqlite = url.startswith("sqlite")

    connect_args = {}
    extra_kwargs = {}
    if is_sqlite:
        connect_args = {"check_same_thread": False}
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool
            extra_kwargs["poolclass"] = StaticPool

    engine = create_engine(
        url,
        echo=False,
        connect_args=connect_args,
        pool_pre_ping=True,
        **extra_kwargs,
    )

    # Enable foreign keys for SQLite test runs
    if is_sqlite:
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


# Default session factory
engine = get_engine()
SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Yields a database session with automatic cleanup and rollback on unhandled error."""
    session = SessionFactory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
