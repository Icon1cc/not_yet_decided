"""PostgreSQL connection pool."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        if not settings.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. "
                "Add it to your .env file, e.g.:\n"
                "  DATABASE_URL=postgresql://user:password@localhost:5432/competitor_matcher"
            )
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=settings.database_url,
        )
        logger.info("PostgreSQL connection pool created.")
    return _pool


@contextmanager
def get_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """Yield a connection from the pool, auto-commit or rollback on exit."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def get_cursor(conn: psycopg2.extensions.connection):
    """Return a RealDictCursor (rows as dicts)."""
    return conn.cursor(cursor_factory=RealDictCursor)
