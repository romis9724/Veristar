"""PostgreSQL 연결 유틸리티.

환경변수:
    DATABASE_URL  PostgreSQL DSN
                  기본: postgresql://veristar:veristar@localhost:5432/veristar
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

_DEFAULT_DSN = "postgresql://veristar:veristar@localhost:5433/veristar"
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _dsn() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_DSN)


def get_conn() -> psycopg.Connection[dict[str, object]]:  # type: ignore[type-arg]
    """dict row factory 적용된 psycopg3 연결을 반환한다."""
    return psycopg.connect(_dsn(), row_factory=dict_row)  # type: ignore[return-value]


def init_schema(conn: psycopg.Connection | None = None) -> None:
    """schema.sql을 실행해 테이블을 생성한다(IF NOT EXISTS)."""
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    if conn is not None:
        conn.execute(sql)
        conn.commit()
        return
    with get_conn() as c:
        c.execute(sql)
        c.commit()


def is_available() -> bool:
    """PostgreSQL에 연결 가능한지 확인한다."""
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False
