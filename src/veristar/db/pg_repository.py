"""PostgreSQL 기반 GraphRepository 구현.

InMemoryGraphRepository와 동일한 인터페이스를 제공하며
검색에는 벡터 유사도(entity linker)와 pg full-text를 함께 사용한다.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from pgvector.psycopg import register_vector  # type: ignore[import-untyped]

from veristar.ontology.enums import Grade, Predicate, SourceType, Status
from veristar.ontology.models import (
    Award,
    Entity,
    Event,
    Group,
    Organization,
    Person,
    Source,
    Statement,
    Work,
)

from .vector_store import VectorStore

logger = logging.getLogger(__name__)

_CTOR: dict[str, Any] = {
    "Person": Person,
    "Group": Group,
    "Organization": Organization,
    "Work": Work,
    "Event": Event,
    "Award": Award,
}


def _row_to_entity(row: dict[str, Any]) -> Entity:
    ctor = _CTOR.get(row["type"], Person)
    extra = row.get("extra") or {}
    return ctor(
        id=row["id"],
        name=row["name"],
        aliases=list(row.get("aliases") or []),
        created_at=row["created_at"],
        **{k: v for k, v in extra.items() if k in ctor.model_fields},
    )


def _row_to_statement(row: dict[str, Any]) -> Statement:
    return Statement(
        id=row["id"],
        subject=row["subject"],
        predicate=Predicate(row["predicate"]),
        object=row["object"],
        grade=Grade(row["grade"]),
        status=Status(row["status"]),
        sources=list(row.get("sources") or []),
        valid_from=row.get("valid_from"),
        valid_to=row.get("valid_to"),
        asserted_at=row.get("asserted_at"),
        sensitive=bool(row.get("sensitive", False)),
        qualifier=row.get("qualifier"),
    )


def _row_to_source(row: dict[str, Any]) -> Source:
    return Source(
        id=row["id"],
        source_type=SourceType(row["source_type"]),
        publisher=row["publisher"],
        url=row["url"],
        title=row["title"],
        published_at=row.get("published_at"),
        retrieved_at=row.get("retrieved_at"),
        license=row.get("license"),
    )


class PostgreSQLGraphRepository:
    """PostgreSQL + pgvector 기반 그래프 저장소.

    InMemoryGraphRepository 프로토콜 호환.
    entity 검색은 벡터 유사도(nomic-embed-text)를 우선 사용하고
    임베딩이 없는 경우 ILIKE 폴백한다.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        register_vector(conn)
        self._conn = conn
        self._vs = VectorStore(conn)

    # ─── 기본 CRUD ─────────────────────────────────────────────────────────────

    def get_entity(self, entity_id: str) -> Entity | None:
        row = self._conn.execute(
            "SELECT * FROM entities WHERE id = %s", (entity_id,)
        ).fetchone()
        return _row_to_entity(row) if row else None

    def get_source(self, source_id: str) -> Source | None:
        row = self._conn.execute(
            "SELECT * FROM sources WHERE id = %s", (source_id,)
        ).fetchone()
        return _row_to_source(row) if row else None

    # ─── 검색 ──────────────────────────────────────────────────────────────────

    def search_entities(self, query: str, limit: int = 20) -> list[Entity]:
        """이름·별칭 기반 텍스트 검색 (ILIKE + alias 배열 검색)."""
        q = query.strip()
        if not q:
            return []
        rows = self._conn.execute(
            """
            SELECT * FROM entities
            WHERE name ILIKE %s
               OR %s = ANY(aliases)
            ORDER BY length(name)
            LIMIT %s
            """,
            (f"%{q}%", q, limit),
        ).fetchall()
        return [_row_to_entity(r) for r in rows]

    def find_mentioned(self, text: str, limit: int = 5) -> list[Entity]:
        """텍스트에 언급된 엔티티를 벡터 유사도로 탐색한다.

        1순위: 벡터 유사도 (nomic-embed-text cosine similarity)
        2순위: 이름 부분일치 ILIKE (임베딩 없을 때 fallback)

        기존 InMemoryGraphRepository와 달리 짧은 이름의 false-positive를
        cosine threshold로 차단해 entity linking 정확도를 높인다.
        """
        t = text.strip()
        if not t:
            return []

        # 1순위: 벡터 검색
        vec_results = self._vs.find_similar_entities(t, limit=limit)
        if vec_results:
            ids = [r[0] for r in vec_results]
            rows = self._conn.execute(
                "SELECT * FROM entities WHERE id = ANY(%s)", (ids,)
            ).fetchall()
            by_id = {r["id"]: _row_to_entity(r) for r in rows}
            return [by_id[eid] for eid, _, _ in vec_results if eid in by_id]

        # 2순위: ILIKE fallback (임베딩 미적재 환경)
        rows = self._conn.execute(
            """
            SELECT * FROM entities
            WHERE name = ANY(
                SELECT unnest(string_to_array(%s, ' '))
            )
            OR name ILIKE %s
            ORDER BY length(name) DESC
            LIMIT %s
            """,
            (t, f"%{t[:20]}%", limit),
        ).fetchall()
        return [_row_to_entity(r) for r in rows]

    # ─── Statement 조회 ────────────────────────────────────────────────────────

    def statements_of(self, entity_id: str) -> list[Statement]:
        rows = self._conn.execute(
            "SELECT * FROM statements WHERE subject = %s OR object = %s",
            (entity_id, entity_id),
        ).fetchall()
        return [_row_to_statement(r) for r in rows]

    def outgoing(self, entity_id: str) -> list[Statement]:
        rows = self._conn.execute(
            "SELECT * FROM statements WHERE subject = %s", (entity_id,)
        ).fetchall()
        return [_row_to_statement(r) for r in rows]

    def incoming(self, entity_id: str) -> list[Statement]:
        rows = self._conn.execute(
            "SELECT * FROM statements WHERE object = %s", (entity_id,)
        ).fetchall()
        return [_row_to_statement(r) for r in rows]

    # ─── Upsert ────────────────────────────────────────────────────────────────

    def upsert_entity(self, entity: Entity) -> None:
        # mode="json" 으로 date 등 비직렬화 타입을 JSON 호환 형태로 변환
        extra = entity.model_dump(
            mode="json", exclude={"id", "type", "name", "aliases", "created_at"}
        )
        self._conn.execute(
            """
            INSERT INTO entities (id, type, name, aliases, created_at, extra)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
              SET type = EXCLUDED.type,
                  name = EXCLUDED.name,
                  aliases = EXCLUDED.aliases,
                  extra = EXCLUDED.extra
            """,
            (
                entity.id,
                entity.type,
                entity.name,
                list(entity.aliases),
                entity.created_at,
                psycopg.types.json.Jsonb(extra),
            ),
        )

    def upsert_source(self, source: Source) -> None:
        self._conn.execute(
            """
            INSERT INTO sources (id, source_type, publisher, url, title,
                                  published_at, retrieved_at, license)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
              SET source_type = EXCLUDED.source_type,
                  publisher   = EXCLUDED.publisher,
                  url         = EXCLUDED.url,
                  title       = EXCLUDED.title
            """,
            (
                source.id,
                source.source_type,
                source.publisher,
                source.url,
                source.title,
                source.published_at,
                source.retrieved_at,
                source.license,
            ),
        )

    def upsert_statement(self, stmt: Statement) -> None:
        self._conn.execute(
            """
            INSERT INTO statements (id, subject, predicate, object, grade,
                                     status, sources, valid_from, valid_to,
                                     asserted_at, sensitive, qualifier)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
              SET grade       = EXCLUDED.grade,
                  status      = EXCLUDED.status,
                  sensitive   = EXCLUDED.sensitive
            """,
            (
                stmt.id,
                stmt.subject,
                stmt.predicate,
                stmt.object,
                stmt.grade,
                stmt.status,
                list(stmt.sources),
                stmt.valid_from,
                stmt.valid_to,
                stmt.asserted_at,
                stmt.sensitive,
                stmt.qualifier,
            ),
        )

    def commit(self) -> None:
        self._conn.commit()

    # ─── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, int]:
        def count(table: str) -> int:
            row = self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            return int(row["n"]) if row else 0

        return {
            "entities": count("entities"),
            "sources": count("sources"),
            "statements": count("statements"),
            "vault_docs": count("vault_docs"),
        }
