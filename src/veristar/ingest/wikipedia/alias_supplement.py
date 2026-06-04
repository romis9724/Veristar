"""Wikipedia 한국어 별칭 보완기.

파이프라인 보조 단계: 시드 JSON의 각 엔티티에 kowiki redirect 별칭을 추가한다.
추가 "사실"을 만들지 않고 이름 변형(redirect 제목)만 aliases에 붙인다.

사용법 (CLI):
    python -m veristar.ingest.wikipedia.alias_supplement \\
        --seed data/seed/wikidata_seed.json --sleep 1.5
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from veristar.ingest.wikidata.seed import write_seed
from veristar.ontology.graph import load_graph
from veristar.ontology.models import Entity

from .client import HttpWikipediaClient, WikipediaClient

logger = logging.getLogger(__name__)

_WD_PREFIX = "wd:"


def _bare_qid(entity_id: str) -> str | None:
    """'wd:Q123' → 'Q123'. Wikidata 엔티티가 아니면 None."""
    if entity_id.startswith(_WD_PREFIX):
        return entity_id[len(_WD_PREFIX) :]
    return None


def _patch_aliases(entity: Entity, new_aliases: list[str]) -> Entity:
    """엔티티에 새 별칭을 추가한 복사본을 반환한다."""
    merged = list(entity.aliases) + new_aliases
    return entity.model_copy(update={"aliases": merged})


def supplement_seed(
    seed_path: Path,
    client: WikipediaClient,
    *,
    sleep_sec: float = 1.5,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """시드 파일의 각 엔티티에 Wikipedia 별칭을 보완한다.

    Returns:
        {entity_id: [추가된 alias 목록]}  — 변경이 없으면 빈 dict.

    Notes:
        - dry_run=True이면 파일을 쓰지 않고 변경 예정만 반환한다.
        - 실제 Wikipedia API를 호출하므로 sleep_sec 텀을 두어 rate-limit을 피한다.
    """
    doc = load_graph(seed_path)
    added: dict[str, list[str]] = {}

    for entity in doc.entities:
        qid = _bare_qid(entity.id)
        if qid is None:
            continue

        try:
            kowiki_title = client.fetch_kowiki_title(qid)
        except OSError as exc:
            logger.warning("kowiki title fetch failed for %s: %s", qid, exc)
            continue

        if not kowiki_title:
            logger.debug("%s: no kowiki sitelink, skipped", qid)
            continue

        time.sleep(sleep_sec)

        try:
            redirects = client.fetch_redirects(kowiki_title)
        except OSError as exc:
            logger.warning("redirect fetch failed for %s (%s): %s", qid, kowiki_title, exc)
            continue

        existing_lower = {a.lower() for a in entity.aliases} | {entity.name.lower()}
        new_aliases = [r for r in redirects if r.lower() not in existing_lower]

        if new_aliases:
            added[entity.id] = new_aliases
            logger.info("%s (%s): +%d aliases", entity.id, entity.name, len(new_aliases))

        time.sleep(sleep_sec)

    if not dry_run and added:
        updated_entities = [
            _patch_aliases(e, added[e.id]) if e.id in added else e for e in doc.entities
        ]
        updated_doc = doc.model_copy(update={"entities": updated_entities})
        write_seed(updated_doc, seed_path)
        logger.info("wrote updated seed: %s", seed_path)

    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wikipedia 한국어 별칭 보완기")
    parser.add_argument("--seed", default="data/seed/wikidata_seed.json", help="시드 JSON 경로")
    parser.add_argument("--sleep", type=float, default=1.5, help="API 호출 간 대기 시간(초)")
    parser.add_argument("--dry-run", action="store_true", help="파일 쓰기 없이 변경 예정만 출력")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    with HttpWikipediaClient() as client:
        added = supplement_seed(
            Path(args.seed),
            client,
            sleep_sec=args.sleep,
            dry_run=args.dry_run,
        )

    total = sum(len(v) for v in added.values())
    logger.info(
        "done: %d entities updated, %d aliases added%s",
        len(added),
        total,
        " (dry-run)" if args.dry_run else "",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
