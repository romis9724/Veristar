"""CLI: 외부 검색 → 도메인 분류 → collection_targets 적재.

사용법:
    python -m veristar.ingest.search.discover --query "스트레이 키즈 신곡"
    python -m veristar.ingest.search.discover --query "블랙핑크" --limit 20 --include-rumor

흐름 (CLAUDE.md §4-1·§4-3 정합):
    1. NaverSearchProvider.search(query)
    2. DomainGrading.classify(url) → OFFICIAL/REPORTED/RUMOR
    3. OFFICIAL/REPORTED만 collection_targets에 upsert (RUMOR는 --include-rumor 필요)
    4. id='search:<sha1(url)>', extra={'search_query': query, 'grade_hint': 'OFFICIAL', ...}
    5. 다음 cron 사이클에서 collectors.runner가 URL 크롤링 → vault → 검증
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from collections import Counter
from dataclasses import dataclass

from veristar.ontology.enums import Grade

from .base import SearchProvider, SearchResult
from .domain_grading import DomainGrading, DomainVerdict
from .naver import NaverSearchProvider

logger = logging.getLogger(__name__)


@dataclass
class DiscoverReport:
    query: str
    found: int = 0
    by_grade: Counter[str] = None  # type: ignore[assignment]
    registered: int = 0
    skipped_rumor: int = 0
    blocked: int = 0
    errors: int = 0

    def __post_init__(self) -> None:
        if self.by_grade is None:
            self.by_grade = Counter()

    def summary(self) -> str:
        grades = " ".join(f"{k}={v}" for k, v in sorted(self.by_grade.items()))
        return (
            f"query={self.query!r} found={self.found} {grades} "
            f"registered={self.registered} skipped_rumor={self.skipped_rumor} "
            f"blocked={self.blocked} err={self.errors}"
        )


def _target_id(url: str) -> str:
    return "search:" + hashlib.sha1(url.encode()).hexdigest()[:16]


def discover(
    query: str,
    *,
    provider: SearchProvider | None = None,
    grading: DomainGrading | None = None,
    limit: int = 10,
    include_rumor: bool = False,
    dry_run: bool = False,
) -> DiscoverReport:
    """검색 → 분류 → collection_targets 적재."""
    if provider is None:
        provider = NaverSearchProvider()
    if grading is None:
        grading = DomainGrading()

    report = DiscoverReport(query=query)
    results = provider.search(query, limit=limit)
    report.found = len(results)
    if not results:
        return report

    # PG 사용 불가 시 dry_run 모드로 강제
    upsertable: list[tuple[SearchResult, DomainVerdict]] = []
    for res in results:
        verdict = grading.classify(res.url)
        report.by_grade[verdict.grade.value] += 1
        if verdict.blocked:
            report.blocked += 1
            continue
        if verdict.grade == Grade.RUMOR and not include_rumor:
            report.skipped_rumor += 1
            continue
        upsertable.append((res, verdict))

    if dry_run or not upsertable:
        for res, verdict in upsertable:
            logger.info("[DRY] %s [%s] %s", verdict.grade.value, verdict.domain, res.title[:60])
        return report

    # 실제 upsert
    try:
        from veristar.db.connection import get_conn, is_available
        from veristar.db.targets_repository import CollectionTargetsRepository

        if not is_available():
            logger.warning("PG 사용 불가 — dry-run으로 폴백")
            return report

        # priority 차등: OFFICIAL=10, REPORTED=5, RUMOR=1
        priority_for = {Grade.OFFICIAL: 10, Grade.REPORTED: 5, Grade.RUMOR: 1}

        with get_conn() as conn:
            repo = CollectionTargetsRepository(conn)  # type: ignore[arg-type]
            for res, verdict in upsertable:
                tid = _target_id(res.url)
                # collection_targets 스키마: id, name, namu_title, youtube_channel,
                # instagram, twitter, wikidata_qid, category, status, priority
                # 검색 결과는 URL 직접 수집이므로 name=제목, extra에 url+query 보관
                target = {
                    "id": tid,
                    "name": res.title[:200] or verdict.domain,
                    "category": f"search_{verdict.grade.value}",
                    "priority": priority_for[verdict.grade],
                }
                try:
                    repo.upsert(target)
                    # extra에 URL과 검색 메타 저장 (재처리·디버깅용)
                    conn.execute(
                        "UPDATE collection_targets SET extra = extra || %s::jsonb WHERE id = %s",
                        (
                            _json_extra(res, verdict, query),
                            tid,
                        ),
                    )
                    report.registered += 1
                except Exception as exc:
                    logger.warning("upsert 실패 %s: %s", tid, exc)
                    report.errors += 1
            repo.commit()
    except Exception as exc:
        logger.error("discover PG 동작 중 오류: %s", exc)
        report.errors += 1

    return report


def _json_extra(res: SearchResult, verdict: DomainVerdict, query: str) -> str:
    """collection_targets.extra JSONB에 머지할 페이로드."""
    import json

    payload = {
        "search_query": query,
        "search_url": res.url,
        "search_source": res.source,
        "search_snippet": res.snippet[:500],
        "domain": verdict.domain,
        "grade_hint": verdict.grade.value,
        "source_type_hint": verdict.source_type.value,
    }
    if res.published:
        payload["published"] = res.published.isoformat()
    return json.dumps(payload, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="외부 검색 → collection_targets 자동 적재")
    parser.add_argument("--query", required=True, help="검색 쿼리 (한글 OK)")
    parser.add_argument("--limit", type=int, default=10, help="kind당 결과 수 (기본 10)")
    parser.add_argument(
        "--include-rumor",
        action="store_true",
        help="RUMOR 등급(블로그·커뮤니티)도 큐에 포함 (기본 OFF, 답변 입력 안 됨)",
    )
    parser.add_argument("--dry-run", action="store_true", help="PG 쓰기 없이 분류 결과만 출력")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    report = discover(
        args.query,
        limit=args.limit,
        include_rumor=args.include_rumor,
        dry_run=args.dry_run,
    )
    logger.info("완료: %s", report.summary())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
