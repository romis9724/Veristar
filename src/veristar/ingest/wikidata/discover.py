"""SPARQL 자동 발견 CLI — 한국 연예인을 collection_targets에 적재.

흐름:
    WDQS SPARQL (직업별) → DiscoveredEntity → collection_targets upsert (pending)

사용법:
    python -m veristar.ingest.wikidata.discover \\
        --occupations singer,actor,entertainer,creator,group \\
        [--no-kowiki-filter]   # sitelink 필터 해제 (상한 없음·노이즈↑)

기존 그래프 적재는 건드리지 않는다 — 수집 대상 목록만 채운다.
실제 수집은 runner.py, 그래프 BFS는 build_seed가 담당.
"""

from __future__ import annotations

import argparse
import logging

from veristar.db.connection import get_conn, init_schema, is_available
from veristar.db.targets_repository import CollectionTargetsRepository

from .sparql import (
    OCCUPATION_GROUPS,
    DiscoveredEntity,
    HttpSparqlRunner,
    discover_korean_celebrities,
)

logger = logging.getLogger(__name__)

_DEFAULT_OCCUPATIONS = ["singer", "actor", "entertainer", "creator", "group"]


def _to_target(d: DiscoveredEntity) -> dict[str, object]:
    return {
        "id": f"wd:{d.qid}",
        "name": d.name,
        "namu_title": d.kowiki_title or d.name,
        "wikidata_qid": f"wd:{d.qid}",
        "category": d.category,
        "status": "pending",
        "priority": 0,
    }


def run_discovery(
    occupations: list[str],
    *,
    require_kowiki: bool = True,
) -> tuple[int, int]:
    """SPARQL 발견 → collection_targets 적재.

    Returns:
        (발견 수, 적재 수)
    """
    if not is_available():
        logger.error("PostgreSQL 연결 불가 (DATABASE_URL 확인)")
        return 0, 0

    init_schema()

    with HttpSparqlRunner() as runner:
        discovered = discover_korean_celebrities(runner, occupations, require_kowiki=require_kowiki)

    if not discovered:
        logger.info("발견된 대상 없음")
        return 0, 0

    with get_conn() as conn:
        repo = CollectionTargetsRepository(conn)
        for d in discovered:
            repo.upsert(_to_target(d))
        repo.commit()
        stats = repo.stats()

    logger.info("적재 완료: %d명 발견, collection_targets stats=%s", len(discovered), stats)
    return len(discovered), len(discovered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wikidata SPARQL 한국 연예인 발견")
    parser.add_argument(
        "--occupations",
        default=",".join(_DEFAULT_OCCUPATIONS),
        help=f"콤마 구분 직업 카테고리. 가능: {','.join(OCCUPATION_GROUPS)},group",
    )
    parser.add_argument(
        "--no-kowiki-filter",
        action="store_true",
        help="kowiki sitelink 필터 해제 (전체 발견, 노이즈 증가)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    occupations = [o.strip() for o in args.occupations.split(",") if o.strip()]
    found, loaded = run_discovery(
        occupations,
        require_kowiki=not args.no_kowiki_filter,
    )
    logger.info("완료: 발견 %d · 적재 %d", found, loaded)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
