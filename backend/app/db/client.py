"""PostgreSQL connection — pure Python (pg8000), works on Vercel Lambda."""

from __future__ import annotations

import logging
import ssl
from contextlib import contextmanager
from typing import Generator
from urllib.parse import parse_qs, urlparse

import pg8000.dbapi

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

_conn: pg8000.dbapi.Connection | None = None


def _get_conn() -> pg8000.dbapi.Connection:
    global _conn
    if _conn is not None:
        try:
            _conn.run("SELECT 1")
            return _conn
        except Exception:
            _conn = None

    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to your .env file:\n"
            "  DATABASE_URL=postgresql://user:password@host:5432/dbname"
        )

    url = urlparse(settings.database_url)
    params = parse_qs(url.query)
    ssl_context = None
    if params.get("sslmode", [""])[0] == "require":
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    _conn = pg8000.dbapi.connect(
        host=url.hostname or "localhost",
        port=url.port or 5432,
        database=(url.path or "/postgres").lstrip("/"),
        user=url.username or "postgres",
        password=url.password or "",
        ssl_context=ssl_context,
    )
    logger.info("PostgreSQL connected (%s:%s).", url.hostname, url.port or 5432)
    return _conn


@contextmanager
def get_connection() -> Generator[pg8000.dbapi.Connection, None, None]:
    """Yield a connection; commit on success, rollback on error."""
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_cursor(conn: pg8000.dbapi.Connection) -> pg8000.dbapi.Cursor:
    return conn.cursor()


def rows_as_dicts(cursor: pg8000.dbapi.Cursor) -> list[dict]:
    """Convert cursor rows (tuples) to dicts using column names."""
    if cursor.description is None:
        return []
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
