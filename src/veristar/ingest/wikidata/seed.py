"""시드 오케스트레이션: 루트 QID에서 확장 → 매핑 → 검증 → JSON 기록.

scope→fetch→map→assemble→validate(load_graph와 동일 규칙)→write.
"""

from __future__ import annotations

import argparse
import logging
from collections import deque
from datetime import datetime
from pathlib import Path

from veristar.graph import merge
from veristar.ontology.graph import GraphDocument, GraphValidationError, load_graph
from veristar.ontology.models import Entity, Source, Statement

from .client import HttpWikidataClient, WikidataClient
from .mapper import map_item
from .mapping import DEFAULT_MAPPING, WD_PREFIX, WikidataMapping

logger = logging.getLogger(__name__)


def _bare_qid(value: str) -> str:
    """'wd:Q42' → 'Q42'."""
    return value[len(WD_PREFIX) :] if value.startswith(WD_PREFIX) else value


def build_seed(
    client: WikidataClient,
    root_qids: list[str],
    *,
    retrieved_at: datetime,
    mapping: WikidataMapping = DEFAULT_MAPPING,
    require_reference: bool = True,
    max_entities: int = 50,
) -> GraphDocument:
    """루트 QID에서 BFS로 확장하며 시드 그래프를 만든다.

    statement object QID를 따라가되 max_entities로 총량을 제한한다.
    매핑/fetch 실패한 아이템은 건너뛰되 카운트해 로그로 남긴다(조용히 삼키지 않음).
    """
    entities: dict[str, Entity] = {}
    sources: dict[str, Source] = {}
    statements: dict[str, Statement] = {}

    queue: deque[str] = deque(_bare_qid(q) for q in root_qids)
    visited: set[str] = set()
    skipped = 0

    while queue and len(visited) < max_entities:
        qid = queue.popleft()
        if qid in visited:
            continue
        visited.add(qid)

        try:
            item = client.fetch_entity(qid)
        except (KeyError, OSError, ValueError) as exc:
            skipped += 1
            logger.warning("fetch failed for %s: %s", qid, exc)
            continue

        records = map_item(
            item,
            retrieved_at=retrieved_at,
            mapping=mapping,
            require_reference=require_reference,
        )
        if records is None:
            skipped += 1
            logger.info("type not resolved, skipped: %s", qid)
            continue

        entities[records.entity.id] = records.entity
        for src in records.sources:
            sources[src.id] = src
        for stmt in records.statements:
            statements[stmt.id] = stmt
        for obj_qid in records.expand_qids:
            bare = _bare_qid(obj_qid)
            if bare.startswith("Q") and bare not in visited:
                queue.append(bare)

    logger.info(
        "seed built: %d entities, %d statements, %d sources (%d skipped)",
        len(entities),
        len(statements),
        len(sources),
        skipped,
    )

    doc = GraphDocument(
        entities=list(entities.values()),
        sources=list(sources.values()),
        statements=list(statements.values()),
    )
    violations = doc.validate_cross_references()
    if violations:
        raise GraphValidationError(violations)
    return doc


def write_seed(doc: GraphDocument, out_path: str | Path) -> Path:
    """검증된 시드 그래프를 JSON으로 기록."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    return path


def read_roots_file(path: str | Path) -> list[str]:
    """한 줄 1 QID 파일 파싱(`#` 주석·빈 줄 무시)."""
    out: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        token = line.split("#", 1)[0].strip()
        if token:
            out.append(token)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wikidata 시드 수집기 (M2)")
    parser.add_argument("--root", nargs="+", default=[], help="루트 QID (예: Q494721)")
    parser.add_argument("--roots-file", help="루트 QID 목록 파일(한 줄 1개, # 주석)")
    parser.add_argument("--out", default="data/seed/wikidata_seed.json", help="출력 JSON 경로")
    parser.add_argument("--max", type=int, default=50, help="최대 엔티티 수")
    parser.add_argument(
        "--allow-unreferenced",
        action="store_true",
        help="reference 없는 claim도 OFFICIAL로 수용 (기본: skip)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="기존 출력 파일을 무시하고 덮어쓰기 (기본: 있으면 병합/누적)",
    )
    args = parser.parse_args(argv)

    roots = list(args.root)
    if args.roots_file:
        roots += read_roots_file(args.roots_file)
    if not roots:
        parser.error("루트가 없습니다. --root 또는 --roots-file 을 지정하세요.")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    client = HttpWikidataClient()
    try:
        incoming = build_seed(
            client,
            roots,
            retrieved_at=datetime.now(),
            require_reference=not args.allow_unreferenced,
            max_entities=args.max,
        )
    finally:
        client.close()

    out_path = Path(args.out)
    if out_path.exists() and not args.fresh:
        base = load_graph(out_path)
        doc, report = merge(base, incoming)
        logger.info("merged into existing: %s", report.summary())
    else:
        doc = incoming

    violations = doc.validate_cross_references()
    if violations:
        raise GraphValidationError(violations)
    path = write_seed(doc, out_path)
    logger.info(
        "wrote %s (%d entities, %d statements)", path, len(doc.entities), len(doc.statements)
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
