"""M4 뉴스 수집 파이프라인 오케스트레이터.

흐름:
    RSS fetch → 민감 필터 → 엔티티 링크 → LLM 추출 → Statement 생성 → 그래프 병합

공개 RSS만 사용. 원문 복제 없음. 제목에서 사실만 추출.
민감 카테고리는 파이프라인 입구에서 차단 (safety-guidelines.md §1, §5).

사용법 (CLI):
    python -m veristar.ingest.news.pipeline \\
        --feeds config/news_feeds.yaml \\
        --seed data/seed/wikidata_seed.json
"""

from __future__ import annotations

import argparse
import hashlib
import logging
from datetime import datetime
from pathlib import Path

from veristar.graph.merge import merge
from veristar.graph.repository import InMemoryGraphRepository
from veristar.ingest.wikidata.seed import write_seed
from veristar.ontology.enums import Grade, SourceType, Status
from veristar.ontology.graph import GraphDocument, load_graph
from veristar.ontology.models import Source, Statement

from .extractor import ExtractedFact, extract_facts
from .rss import FeedConfig, FeedItem, HttpRssClient, RssClient, load_feed_configs

logger = logging.getLogger(__name__)


def _source_id(url: str) -> str:
    """기사 URL → 짧은 결정적 ID."""
    return "src_news_" + hashlib.sha1(url.encode()).hexdigest()[:12]


def _stmt_id(fact: ExtractedFact, source_id: str) -> str:
    key = f"{fact.subject_id}|{fact.predicate}|{fact.object_id}|{source_id}"
    return "stmt_news_" + hashlib.sha1(key.encode()).hexdigest()[:12]


def fact_to_source(fact: ExtractedFact, source_type: SourceType) -> Source:
    return Source(
        id=_source_id(fact.article_url),
        source_type=source_type,
        publisher=fact.feed_name or "news",
        url=fact.article_url,
        title=fact.article_title,
        published_at=fact.published,
        retrieved_at=datetime.now().date(),
    )


def fact_to_statement(fact: ExtractedFact, source_id: str) -> Statement:
    from veristar.ontology.enums import Predicate

    return Statement(
        id=_stmt_id(fact, source_id),
        subject=fact.subject_id,
        predicate=Predicate(fact.predicate),
        object=fact.object_id,
        grade=Grade.REPORTED,
        status=Status.ACTIVE,
        sources=[source_id],
        valid_from=fact.published,
        sensitive=False,
    )


def run_pipeline(
    seed_path: Path,
    feed_configs: list[FeedConfig],
    rss_client: RssClient,
    *,
    dry_run: bool = False,
    llm_model: str | None = None,
) -> tuple[int, int]:
    """뉴스 파이프라인 실행.

    Returns:
        (추가된 statement 수, 스킵된 아이템 수)
    """
    if not seed_path.exists():
        logger.error("시드 파일이 없습니다: %s", seed_path)
        return 0, 0

    base_doc = load_graph(seed_path)
    repo = InMemoryGraphRepository(base_doc)

    all_sources: dict[str, Source] = {}
    all_statements: dict[str, Statement] = {}
    skipped = 0

    for feed_cfg in feed_configs:
        logger.info("fetching: %s (%s)", feed_cfg.name, feed_cfg.url)
        items: list[FeedItem] = rss_client.fetch_items(feed_cfg.url, feed_cfg.name)
        source_type = SourceType(feed_cfg.source_type)

        for item in items:
            facts = extract_facts(item, repo, model=llm_model)
            if not facts:
                skipped += 1
                continue
            for fact in facts:
                src = fact_to_source(fact, source_type)
                stmt = fact_to_statement(fact, src.id)
                all_sources[src.id] = src
                all_statements[stmt.id] = stmt

    if not all_statements:
        logger.info("no new statements extracted")
        return 0, skipped

    incoming = GraphDocument(
        entities=[],
        sources=list(all_sources.values()),
        statements=list(all_statements.values()),
    )

    merged_doc, report = merge(base_doc, incoming)
    logger.info("merge: %s", report.summary())

    if not dry_run:
        write_seed(merged_doc, seed_path)
        logger.info("wrote updated seed: %s", seed_path)

    return len(all_statements), skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M4 뉴스 사실 추출 파이프라인")
    parser.add_argument(
        "--feeds",
        default="config/news_feeds.yaml",
        help="RSS 피드 설정 파일 (YAML)",
    )
    parser.add_argument(
        "--seed",
        default="data/seed/wikidata_seed.json",
        help="시드 JSON 경로",
    )
    parser.add_argument("--dry-run", action="store_true", help="파일 쓰기 없이 출력만")
    parser.add_argument("--model", default=None, help="LLM 모델 override")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    feed_configs = load_feed_configs(args.feeds)
    if not feed_configs:
        logger.warning("피드 설정이 없습니다: %s", args.feeds)
        return 0

    with HttpRssClient() as rss_client:
        added, skipped = run_pipeline(
            Path(args.seed),
            feed_configs,
            rss_client,
            dry_run=args.dry_run,
            llm_model=args.model,
        )

    logger.info("완료: statement +%d, 스킵 %d", added, skipped)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
