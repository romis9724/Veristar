"""수집 대상(collection_targets) 저장소.

SPARQL 발견 결과를 적재하고, runner.py가 pending 대상을 읽어 수집한다.
pg_repository.py의 psycopg3 dict_row + upsert 패턴을 따른다.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg

logger = logging.getLogger(__name__)


class CollectionTargetsRepository:
    """collection_targets 테이블 CRUD."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert(self, target: dict[str, Any]) -> None:
        """수집 대상 upsert. id 충돌 시 메타는 갱신하되 status는 보존한다."""
        t = "collection_targets"
        self._conn.execute(
            f"""
            INSERT INTO {t}
                (id, name, namu_title, youtube_channel, instagram, twitter,
                 wikidata_qid, category, status, priority)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                    COALESCE(%s, 'pending'), COALESCE(%s, 0))
            ON CONFLICT (id) DO UPDATE
              SET name            = EXCLUDED.name,
                  namu_title      = COALESCE(EXCLUDED.namu_title, {t}.namu_title),
                  youtube_channel = COALESCE(EXCLUDED.youtube_channel, {t}.youtube_channel),
                  instagram       = COALESCE(EXCLUDED.instagram, {t}.instagram),
                  twitter         = COALESCE(EXCLUDED.twitter, {t}.twitter),
                  wikidata_qid    = COALESCE(EXCLUDED.wikidata_qid, {t}.wikidata_qid),
                  category        = COALESCE(EXCLUDED.category, {t}.category)
            """,
            (
                target["id"],
                target["name"],
                target.get("namu_title"),
                target.get("youtube_channel"),
                target.get("instagram"),
                target.get("twitter"),
                target.get("wikidata_qid"),
                target.get("category"),
                target.get("status"),
                target.get("priority"),
            ),
        )

    def list_pending(
        self, limit: int | None = None, category: str | None = None
    ) -> list[dict[str, Any]]:
        """status='pending' 대상을 priority 내림차순으로 반환한다."""
        sql = "SELECT * FROM collection_targets WHERE status = 'pending'"
        params: list[Any] = []
        if category:
            sql += " AND category = %s"
            params.append(category)
        sql += " ORDER BY priority DESC, created_at ASC"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def list_all(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM collection_targets ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def _set_status(self, target_id: str, status: str, touch: bool = False) -> None:
        if touch:
            self._conn.execute(
                "UPDATE collection_targets "
                "SET status = %s, last_collected_at = now() WHERE id = %s",
                (status, target_id),
            )
        else:
            self._conn.execute(
                "UPDATE collection_targets SET status = %s WHERE id = %s",
                (status, target_id),
            )
        self._conn.commit()

    def mark_collecting(self, target_id: str) -> None:
        self._set_status(target_id, "collecting")

    def mark_done(self, target_id: str) -> None:
        self._set_status(target_id, "done", touch=True)

    def mark_failed(self, target_id: str) -> None:
        self._set_status(target_id, "failed", touch=True)

    def commit(self) -> None:
        self._conn.commit()

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM collection_targets").fetchone()
        return int(row["n"]) if row else 0

    def stats(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM collection_targets GROUP BY status"
        ).fetchall()
        return {r["status"]: int(r["n"]) for r in rows}
