"""JSONL 그래프 + Markdown vault → PostgreSQL 마이그레이션.

사용법:
    python -m veristar.db.migrate \\
        --seed data/seed/wikidata_seed.json \\
        --vault vault/ \\
        [--embed]           # 임베딩도 함께 적재 (Ollama 필요)

기존 파일은 삭제하지 않는다 (백업 역할 유지).
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from veristar.ontology.graph import load_graph
from veristar.vault.store import VaultStore

from .connection import get_conn, init_schema
from .pg_repository import PostgreSQLGraphRepository
from .vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class MigrationReport:
    entities: int = 0
    sources: int = 0
    statements: int = 0
    vault_docs: int = 0
    entity_embeddings: int = 0
    vault_embeddings: int = 0

    def summary(self) -> str:
        return (
            f"entities={self.entities} sources={self.sources} "
            f"statements={self.statements} vault_docs={self.vault_docs} "
            f"entity_emb={self.entity_embeddings} vault_emb={self.vault_embeddings}"
        )


def migrate_graph(
    repo: PostgreSQLGraphRepository,
    seed_path: Path,
) -> tuple[int, int, int]:
    """JSONL 그래프 → PostgreSQL entities/sources/statements."""
    doc = load_graph(seed_path)

    for entity in doc.entities:
        repo.upsert_entity(entity)
    repo.commit()
    logger.info("entities: %d", len(doc.entities))

    for source in doc.sources:
        repo.upsert_source(source)
    repo.commit()
    logger.info("sources: %d", len(doc.sources))

    for stmt in doc.statements:
        repo.upsert_statement(stmt)
    repo.commit()
    logger.info("statements: %d", len(doc.statements))

    return len(doc.entities), len(doc.sources), len(doc.statements)


def migrate_vault(
    conn: psycopg.Connection,
    vault_root: Path,
) -> int:
    """Markdown vault → PostgreSQL vault_docs."""
    store = VaultStore(vault_root)
    docs = store.list_docs()
    count = 0
    for doc in docs:
        extra: dict[str, object] = dict(doc.extra)
        conn.execute(
            """
            INSERT INTO vault_docs (
                id, title, content, source_type, source_url,
                entity_refs, published, retrieved, confidence, license, sensitive, extra
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE
              SET content    = EXCLUDED.content,
                  confidence = EXCLUDED.confidence,
                  sensitive  = EXCLUDED.sensitive,
                  extra      = EXCLUDED.extra
            """,
            (
                doc.id,
                doc.title,
                doc.content,
                doc.source_type,
                doc.source_url,
                list(doc.entity_refs),
                doc.published,
                doc.retrieved,
                doc.confidence,
                doc.license,
                doc.sensitive,
                psycopg.types.json.Jsonb(dict(extra)),
            ),
        )
        count += 1
    conn.commit()
    logger.info("vault_docs: %d", count)
    return count


def run_migration(
    seed_path: Path,
    vault_root: Path,
    *,
    embed: bool = False,
) -> MigrationReport:
    report = MigrationReport()

    logger.info("스키마 초기화...")
    init_schema()

    with get_conn() as conn:
        register_vector(conn)
        repo = PostgreSQLGraphRepository(conn)

        logger.info("=== 그래프 마이그레이션 (%s) ===", seed_path)
        e, s, st = migrate_graph(repo, seed_path)
        report.entities = e
        report.sources = s
        report.statements = st

        logger.info("=== vault 마이그레이션 (%s) ===", vault_root)
        report.vault_docs = migrate_vault(conn, vault_root)

        if embed:
            logger.info("=== 임베딩 생성 ===")
            vs = VectorStore(conn)
            report.entity_embeddings = vs.embed_all_entities()
            report.vault_embeddings = vs.embed_all_vault_docs()

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JSONL → PostgreSQL 마이그레이션")
    parser.add_argument("--seed", default="data/seed/wikidata_seed.json")
    parser.add_argument("--vault", default="vault")
    parser.add_argument(
        "--embed",
        action="store_true",
        help="마이그레이션 후 임베딩 생성 (Ollama 필요)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    report = run_migration(
        Path(args.seed),
        Path(args.vault),
        embed=args.embed,
    )
    logger.info("완료: %s", report.summary())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
