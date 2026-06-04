"""M4 뉴스 파이프라인 통합 테스트 (HTTP·LLM 모킹)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from veristar.ingest.news.pipeline import run_pipeline, fact_to_source, fact_to_statement
from veristar.ingest.news.rss import FeedConfig, FeedItem, RssClient
from veristar.ingest.news.extractor import ExtractedFact
from veristar.ontology.enums import Grade, SourceType, Status
from veristar.ontology.graph import GraphDocument, load_graph
from veristar.ontology.models import Group, Source, Statement
from veristar.generate.llm import LLMResult

from datetime import datetime


@pytest.fixture
def minimal_seed(tmp_path: Path) -> Path:
    """엔티티 2개짜리 최소 시드 (파이프라인 테스트용)."""
    doc = GraphDocument(
        entities=[
            Group(id="wd:Q1", name="아티스트 A", created_at=datetime(2024, 1, 1)),
            Group(id="wd:Q2", name="그룹 G", created_at=datetime(2024, 1, 1)),
        ],
        sources=[],
        statements=[],
    )
    seed = tmp_path / "seed.json"
    seed.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    return seed


class FakeRssClient:
    def __init__(self, items: list[FeedItem]) -> None:
        self._items = items

    def fetch_items(self, feed_url: str, feed_name: str = "") -> list[FeedItem]:
        return [FeedItem(i.title, i.url, i.published, i.summary, feed_name) for i in self._items]


def test_pipeline_adds_statements(minimal_seed: Path) -> None:
    items = [
        FeedItem(
            title="아티스트 A 그룹 G 소속 발표",
            url="https://news.example.com/1",
            published=date(2024, 6, 1),
            feed_name="테스트",
        )
    ]
    feed_configs = [FeedConfig(name="테스트", url="https://dummy", source_type="PRESS")]
    llm_response = json.dumps({
        "facts": [{"subject_id": "wd:Q1", "predicate": "memberOf", "object_id": "wd:Q2"}]
    })
    mock_result = LLMResult(ok=True, text=llm_response, model="test", error=None)

    with patch("veristar.ingest.news.extractor.chat", return_value=mock_result):
        added, skipped = run_pipeline(
            minimal_seed,
            feed_configs,
            FakeRssClient(items),
            dry_run=True,
        )

    assert added == 1
    assert skipped == 0


def test_pipeline_dry_run_no_write(minimal_seed: Path) -> None:
    original = minimal_seed.read_text()
    items = [
        FeedItem("아티스트 A 그룹 G 뉴스", "https://x.com/1", date(2024, 1, 1))
    ]
    llm_response = json.dumps({
        "facts": [{"subject_id": "wd:Q1", "predicate": "memberOf", "object_id": "wd:Q2"}]
    })
    mock_result = LLMResult(ok=True, text=llm_response, model="test", error=None)

    with patch("veristar.ingest.news.extractor.chat", return_value=mock_result):
        run_pipeline(
            minimal_seed,
            [FeedConfig("t", "https://dummy", "PRESS")],
            FakeRssClient(items),
            dry_run=True,
        )

    assert minimal_seed.read_text() == original


def test_pipeline_writes_when_not_dry_run(minimal_seed: Path) -> None:
    items = [
        FeedItem("아티스트 A 그룹 G 확인", "https://x.com/2", date(2024, 1, 1))
    ]
    llm_response = json.dumps({
        "facts": [{"subject_id": "wd:Q1", "predicate": "memberOf", "object_id": "wd:Q2"}]
    })
    mock_result = LLMResult(ok=True, text=llm_response, model="test", error=None)

    with patch("veristar.ingest.news.extractor.chat", return_value=mock_result):
        added, _ = run_pipeline(
            minimal_seed,
            [FeedConfig("t", "https://dummy", "PRESS")],
            FakeRssClient(items),
            dry_run=False,
        )

    assert added == 1
    updated = load_graph(minimal_seed)
    assert any(s.grade == Grade.REPORTED for s in updated.statements)


def test_pipeline_no_statements_when_no_facts(minimal_seed: Path) -> None:
    """LLM이 facts: []를 반환하면 statement가 추가되지 않는다."""
    items = [FeedItem("무관한 뉴스", "https://x.com/3", date(2024, 1, 1))]
    mock_result = LLMResult(ok=True, text='{"facts": []}', model="test", error=None)

    with patch("veristar.ingest.news.extractor.chat", return_value=mock_result):
        added, skipped = run_pipeline(
            minimal_seed,
            [FeedConfig("t", "https://dummy", "PRESS")],
            FakeRssClient(items),
            dry_run=True,
        )

    assert added == 0


def test_pipeline_missing_seed_returns_zero(tmp_path: Path) -> None:
    missing = tmp_path / "no_such_file.json"
    added, skipped = run_pipeline(
        missing,
        [FeedConfig("t", "https://dummy", "PRESS")],
        FakeRssClient([]),
    )
    assert added == 0
    assert skipped == 0


def test_fact_to_source_fields() -> None:
    fact = ExtractedFact(
        subject_id="wd:Q1",
        predicate="memberOf",
        object_id="wd:Q2",
        article_title="BTS 뉴스",
        article_url="https://example.com/bts",
        published=date(2024, 3, 1),
        feed_name="연합뉴스",
    )
    src = fact_to_source(fact, SourceType.PRESS)
    assert src.publisher == "연합뉴스"
    assert src.url == "https://example.com/bts"
    assert src.source_type == SourceType.PRESS
    assert src.published_at == date(2024, 3, 1)


def test_fact_to_statement_reported_grade() -> None:
    fact = ExtractedFact(
        subject_id="wd:Q1",
        predicate="memberOf",
        object_id="wd:Q2",
        article_title="뉴스",
        article_url="https://example.com/1",
        published=date(2024, 1, 1),
        feed_name="test",
    )
    stmt = fact_to_statement(fact, "src_id_123")
    assert stmt.grade == Grade.REPORTED
    assert stmt.status == Status.ACTIVE
    assert "src_id_123" in stmt.sources
    assert stmt.sensitive is False
