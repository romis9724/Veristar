"""통합 수집 CLI — 모든 수집기를 순서대로 실행한다.

설정 파일: config/celebrities.yaml

사용법:
    python -m veristar.ingest.collectors.runner \\
        --config config/celebrities.yaml \\
        --vault vault/ \\
        --sources wikipedia,namuwiki,news
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from veristar.vault.store import VaultStore

from .base import CollectResult
from .namuwiki import NamuWikiCollector
from .wikipedia import WikipediaCollector
from .youtube import YouTubeCollector

logger = logging.getLogger(__name__)


def load_celebrity_list(config_path: str | Path) -> list[dict[str, str]]:
    """celebrities.yaml 파싱.

    형식::

        celebrities:
          - name: 아이유
            namu_title: 아이유
            youtube_channel: UCzx8rFWJHzBFfKqSEDmKYSg
            instagram: dlwlrma
            twitter: IUofficial
          - name: BTS 방탄소년단
            namu_title: 방탄소년단
    """
    path = Path(config_path)
    if not path.exists():
        return []

    celebrities: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if stripped.startswith("- name:"):
            if current.get("name"):
                celebrities.append(dict(current))
            current = {"name": stripped[len("- name:"):].strip()}
        elif ":" in stripped and not stripped.startswith("celebrities"):
            k, _, v = stripped.partition(":")
            current[k.strip()] = v.strip()
    if current.get("name"):
        celebrities.append(dict(current))
    return celebrities


def run_all(
    config_path: str | Path,
    vault_root: str | Path,
    sources: list[str],
    feeds_path: str | Path = "config/news_feeds.yaml",
) -> CollectResult:
    """모든 수집기 실행."""
    celebrities = load_celebrity_list(config_path)
    if not celebrities:
        logger.warning("수집 대상이 없습니다: %s", config_path)
        return CollectResult()

    store = VaultStore(vault_root)
    total = CollectResult()

    if "wikipedia" in sources:
        logger.info("=== Wikipedia 수집 시작 ===")
        with WikipediaCollector(store) as collector:
            for cel in celebrities:
                name = cel.get("name", "")
                if name:
                    r = collector.collect(name)
                    total = total.merge(r)
                    logger.info("wikipedia [%s]: saved=%d skipped=%d", name, r.saved, r.skipped)

    if "namuwiki" in sources:
        logger.info("=== 나무위키 수집 시작 ===")
        with NamuWikiCollector(store) as collector:
            for cel in celebrities:
                namu_title = cel.get("namu_title") or cel.get("name", "")
                if namu_title:
                    r = collector.collect(namu_title)
                    total = total.merge(r)
                    logger.info("namuwiki [%s]: +%d", namu_title, r.saved)

    if "news" in sources:
        logger.info("=== 뉴스 수집 시작 ===")
        from veristar.ingest.news.rss import load_feed_configs

        from .news import NewsCollector

        feed_configs = load_feed_configs(feeds_path)
        with NewsCollector(store) as collector:
            for cfg in feed_configs:
                r = collector.collect(cfg.url, feed_name=cfg.name, source_type=cfg.source_type)
                total = total.merge(r)
                logger.info("news [%s]: saved=%d skipped=%d", cfg.name, r.saved, r.skipped)

    if "youtube" in sources:
        logger.info("=== YouTube 수집 시작 ===")
        with YouTubeCollector(store) as collector:
            for cel in celebrities:
                channel_id = cel.get("youtube_channel", "")
                name = cel.get("name", "")
                if channel_id:
                    r = collector.collect(name, channel_id=channel_id)
                elif name:
                    r = collector.collect(f"{name} 공식")
                else:
                    continue
                total = total.merge(r)
                logger.info("youtube [%s]: saved=%d", name, r.saved)

    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="통합 콘텐츠 수집기")
    parser.add_argument("--config", default="config/celebrities.yaml")
    parser.add_argument("--vault", default="vault")
    parser.add_argument(
        "--sources",
        default="wikipedia,namuwiki,news",
        help="수집 소스 (콤마 구분): wikipedia,namuwiki,news,youtube",
    )
    parser.add_argument("--feeds", default="config/news_feeds.yaml")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    sources = [s.strip() for s in args.sources.split(",")]
    result = run_all(args.config, args.vault, sources, args.feeds)
    logger.info(
        "수집 완료: saved=%d skipped=%d errors=%d",
        result.saved, result.skipped, result.errors,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
