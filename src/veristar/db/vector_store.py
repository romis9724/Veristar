"""pgvector 기반 임베딩 저장 및 유사도 검색.

nomic-embed-text (Ollama) → 768-dim 벡터
사용처:
  - 엔티티 링킹 (이름·별칭 벡터로 유사 엔티티 탐색)
  - vault 문서 의미 검색 (RAG 컨텍스트 수집)
  - 중복 문서 감지
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
import psycopg
from pgvector.psycopg import register_vector  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
# bge-m3: 한국어 강한 다국어 임베딩 (1024-dim). nomic-embed-text는 한국어 변별력 없음.
_EMBED_MODEL = os.environ.get("VERISTAR_EMBED_MODEL", "bge-m3")
_EMBED_DIM = int(os.environ.get("VERISTAR_EMBED_DIM", "1024"))
_LINK_THRESHOLD = float(os.environ.get("VERISTAR_LINK_THRESHOLD", "0.6"))


def embed_text(text: str, timeout: float = 30.0) -> list[float] | None:
    """Ollama 임베딩 모델로 텍스트를 벡터화한다 (기본 bge-m3, 1024-dim).

    Returns:
        임베딩 float 리스트, 실패 시 None.
    """
    try:
        resp = httpx.post(
            f"{_OLLAMA_HOST}/api/embeddings",
            json={"model": _EMBED_MODEL, "prompt": text[:2000]},
            timeout=timeout,
        )
        resp.raise_for_status()
        return list(resp.json()["embedding"])
    except Exception as exc:
        logger.warning("embed failed for %r: %s", text[:60], exc)
        return None


class VaultDocResult:
    """벡터 검색 결과."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.id: str = row["id"]
        self.title: str = row["title"]
        self.content: str = row["content"]
        self.source_type: str = row["source_type"]
        self.source_url: str = row["source_url"]
        self.confidence: str = row["confidence"]
        self.sensitive: bool = bool(row.get("sensitive", False))
        self.similarity: float = float(row.get("similarity", 0.0))


class VectorStore:
    """pgvector 인터페이스.

    Args:
        conn: psycopg3 연결 (dict_row factory).
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        register_vector(conn)
        self._conn = conn

    # ─── 엔티티 임베딩 ────────────────────────────────────────────────────────

    def upsert_entity_embedding(self, entity_id: str, text: str) -> bool:
        """엔티티 이름+별칭 텍스트를 임베딩해 저장한다."""
        vec = embed_text(text)
        if vec is None:
            return False
        self._conn.execute(
            "UPDATE entities SET embedding = %s WHERE id = %s",
            (vec, entity_id),
        )
        return True

    def embed_all_entities(self) -> int:
        """embedding이 NULL인 엔티티를 모두 임베딩한다."""
        rows = self._conn.execute(
            "SELECT id, name, aliases FROM entities WHERE embedding IS NULL"
        ).fetchall()
        count = 0
        for row in rows:
            text = row["name"] + " " + " ".join(row["aliases"] or [])
            if self.upsert_entity_embedding(row["id"], text):
                count += 1
        self._conn.commit()
        logger.info("entity embeddings updated: %d", count)
        return count

    def find_similar_entities(
        self, query: str, limit: int = 5, threshold: float | None = None
    ) -> list[tuple[str, str, float]]:
        """쿼리 텍스트와 유사한 엔티티를 벡터 검색으로 반환한다.

        Returns:
            [(entity_id, name, similarity)] — similarity 내림차순.
        """
        th = threshold if threshold is not None else _LINK_THRESHOLD
        vec = embed_text(query)
        if vec is None:
            return []
        rows = self._conn.execute(
            """
            SELECT id, name,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM entities
            WHERE embedding IS NOT NULL
              AND 1 - (embedding <=> %s::vector) >= %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (vec, vec, th, vec, limit),
        ).fetchall()
        return [(r["id"], r["name"], float(r["similarity"])) for r in rows]

    # ─── Vault 문서 임베딩 ────────────────────────────────────────────────────

    def upsert_vault_embedding(self, doc_id: str, title: str, content: str) -> bool:
        """vault 문서 임베딩을 저장한다."""
        text = f"{title}\n{content[:800]}"
        vec = embed_text(text)
        if vec is None:
            return False
        self._conn.execute(
            "UPDATE vault_docs SET embedding = %s WHERE id = %s",
            (vec, doc_id),
        )
        return True

    def embed_all_vault_docs(self) -> int:
        """embedding이 NULL인 vault 문서를 모두 임베딩한다."""
        rows = self._conn.execute(
            "SELECT id, title, content FROM vault_docs WHERE embedding IS NULL"
        ).fetchall()
        count = 0
        for row in rows:
            if self.upsert_vault_embedding(row["id"], row["title"], row["content"]):
                count += 1
        self._conn.commit()
        logger.info("vault_doc embeddings updated: %d", count)
        return count

    def search_vault_docs(
        self,
        query: str,
        limit: int = 5,
        source_type: str | None = None,
        min_confidence: str | None = None,
    ) -> list[VaultDocResult]:
        """쿼리와 의미적으로 유사한 vault 문서를 반환한다 (RAG 컨텍스트용)."""
        vec = embed_text(query)
        if vec is None:
            return []
        # psycopg3은 %s 플레이스홀더 사용 (PostgreSQL 네이티브 $N 아님)
        extra_filters: list[str] = []
        extra_params: list[Any] = []
        if source_type:
            extra_filters.append("source_type = %s")
            extra_params.append(source_type)
        if min_confidence:
            order = ["unverified", "low", "medium", "high"]
            valid = [c for c in order if order.index(c) >= order.index(min_confidence)]
            extra_filters.append("confidence = ANY(%s::text[])")
            extra_params.append(valid)
        where_parts = ["embedding IS NOT NULL"] + extra_filters
        where = " AND ".join(where_parts)
        rows = self._conn.execute(
            f"""
            SELECT id, title, content, source_type, source_url, confidence, sensitive,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM vault_docs
            WHERE {where}
            ORDER BY embedding <=> %s::vector
            LIMIT {limit}
            """,  # noqa: S608
            [vec, *extra_params, vec],
        ).fetchall()
        return [VaultDocResult(r) for r in rows]

    def find_duplicate_vault_docs(self, threshold: float = 0.96) -> list[tuple[str, str, float]]:
        """임베딩 유사도가 매우 높은 (거의 동일한) 문서 쌍을 찾는다."""
        rows = self._conn.execute(
            """
            SELECT a.id AS id_a, b.id AS id_b,
                   1 - (a.embedding <=> b.embedding) AS similarity
            FROM vault_docs a
            JOIN vault_docs b ON a.id < b.id
            WHERE a.embedding IS NOT NULL
              AND b.embedding IS NOT NULL
              AND 1 - (a.embedding <=> b.embedding) >= %s
            ORDER BY similarity DESC
            LIMIT 50
            """,
            (threshold,),
        ).fetchall()
        return [(r["id_a"], r["id_b"], float(r["similarity"])) for r in rows]
