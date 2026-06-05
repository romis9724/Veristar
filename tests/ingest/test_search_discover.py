"""discover() 통합 단위 테스트 — MockProvider로 전체 흐름 검증 (PG 미사용)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from veristar.ingest.search.base import SearchResult
from veristar.ingest.search.discover import _target_id, discover
from veristar.ingest.search.domain_grading import DomainGrading


class _MockProvider:
    name = "mock"

    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results

    def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        return self._results[:limit]


@pytest.fixture
def grading(tmp_path: Path) -> DomainGrading:
    cfg = tmp_path / "g.yaml"
    cfg.write_text(
        "official: [smtown.com]\nreported: [news.naver.com]\nblocked: [bad.example]\n",
        encoding="utf-8",
    )
    return DomainGrading(cfg)


def _results() -> list[SearchResult]:
    return [
        SearchResult(
            url="https://smtown.com/artist/aespa",
            title="에스파 공식 페이지",
            snippet="에스파 멤버 소개",
            source="naver_webkr",
        ),
        SearchResult(
            url="https://news.naver.com/article/001",
            title="에스파 신곡 발표",
            snippet="에스파가 신곡을 발표했다",
            source="naver_news",
            published=datetime(2026, 6, 4),
        ),
        SearchResult(
            url="https://blog.naver.com/random/post",
            title="에스파 콘서트 후기",
            snippet="개인 후기",
            source="naver_blog",
        ),
        SearchResult(
            url="https://bad.example/spam",
            title="스팸",
            snippet="스팸",
            source="naver_webkr",
        ),
    ]


def test_dry_run_classifies_without_pg(grading: DomainGrading) -> None:
    """dry_run=True면 PG 없이도 분류만 수행, registered=0."""
    report = discover(
        "에스파",
        provider=_MockProvider(_results()),
        grading=grading,
        dry_run=True,
    )
    assert report.found == 4
    assert report.by_grade["OFFICIAL"] == 1
    assert report.by_grade["REPORTED"] == 1
    assert report.by_grade["RUMOR"] == 2  # blog + bad
    assert report.blocked == 1  # bad.example
    assert report.skipped_rumor == 1  # blog (bad는 blocked로 먼저 카운트)
    assert report.registered == 0


def test_include_rumor_promotes_blog_to_upsertable(grading: DomainGrading) -> None:
    """--include-rumor 옵션이면 RUMOR도 큐 후보가 됨 (blocked는 여전히 차단)."""
    report = discover(
        "에스파",
        provider=_MockProvider(_results()),
        grading=grading,
        include_rumor=True,
        dry_run=True,
    )
    # blog는 RUMOR지만 통과, bad는 blocked
    assert report.skipped_rumor == 0
    assert report.blocked == 1


def test_empty_results_returns_zero_report(grading: DomainGrading) -> None:
    report = discover(
        "쿼리",
        provider=_MockProvider([]),
        grading=grading,
        dry_run=True,
    )
    assert report.found == 0
    assert report.registered == 0


def test_target_id_is_stable() -> None:
    """동일 URL은 항상 같은 id (멱등 upsert)."""
    assert _target_id("https://smtown.com/x") == _target_id("https://smtown.com/x")
    assert _target_id("https://a.com") != _target_id("https://b.com")
    assert _target_id("https://a.com").startswith("search:")
