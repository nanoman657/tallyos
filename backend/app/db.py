"""
PostgreSQL access via psycopg 3.

Rows come back as dicts and NUMERIC columns load as Python floats so the
forecasting / finance code can do plain arithmetic on them.
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg.types.numeric import FloatLoader

from .config import get_settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Db:
    """Small helper around a psycopg connection: dict rows, insert/update sugar."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def all(self, sql: str, params: Iterable[Any] = ()) -> list:
        with self.conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
        with self.conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchone()

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self.conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.rowcount

    def insert(self, table: str, row: dict) -> dict:
        cols = ", ".join(row)
        marks = ", ".join(["%s"] * len(row))
        return self.one(
            f"INSERT INTO {table} ({cols}) VALUES ({marks}) RETURNING *",
            [_adapt(v) for v in row.values()],
        )

    def update(self, table: str, row_id: int, changes: dict) -> Optional[dict]:
        if not changes:
            return self.one(f"SELECT * FROM {table} WHERE id = %s", [row_id])
        sets = ", ".join(f"{k} = %s" for k in changes)
        return self.one(
            f"UPDATE {table} SET {sets} WHERE id = %s RETURNING *",
            [*(_adapt(v) for v in changes.values()), row_id],
        )


def _adapt(value: Any) -> Any:
    # Lists/dicts go into JSONB columns.
    return Jsonb(value) if isinstance(value, (list, dict)) else value


def connect(database_url: Optional[str] = None) -> psycopg.Connection:
    # Session time zone = shop time zone, so now() / TIMESTAMP defaults are shop-local like the rest of the data.
    conn = psycopg.connect(database_url or get_settings().database_url, row_factory=dict_row,
                           options=f"-c TimeZone={get_settings().shop_timezone}")
    conn.adapters.register_loader("numeric", FloatLoader)
    return conn


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_PATH.read_text())
    conn.commit()


@contextmanager
def session(database_url: Optional[str] = None) -> Iterator[Db]:
    """Unit of work: commit on success, roll back on error."""
    conn = connect(database_url)
    try:
        yield Db(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db() -> Iterator[Db]:
    """FastAPI dependency."""
    with session() as db:
        yield db
