"""M4 뉴스 사실 추출기 테스트 (LLM 모킹)."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import pytest

from veristar.ingest.news.extractor import extract_facts
from veristar.ingest.news.rss import FeedItem
from veristar.generate.llm import LLMResult


@pytest.fixture
def feed_item_bts_award() -> FeedItem:
    return FeedItem(
        title="BTS, 빌보드 뮤직 어워드 수상",
        url="https://news.example.com/bts-award",
        published=date(2024, 5, 10),
        feed_name="테스트 피드",
    )


@pytest.fixture
def feed_item_sensitive() -> FeedItem:
    return FeedItem(
        title="아이돌 열애설 포착",
        url="https://news.example.com/romance",
        published=date(2024, 5, 11),
        feed_name="테스트 피드",
    )


@pytest.fixture
def feed_item_single_entity() -> FeedItem:
    """엔티티가 1개뿐 → statement 생성 불가."""
    return FeedItem(
        title="BTS 팬미팅 성료",
        url="https://news.example.com/bts-fanmeeting",
        published=date(2024, 5, 12),
        feed_name="테스트 피드",
    )


def test_sensitive_title_returns_empty(repo, feed_item_sensitive) -> None:
    facts = extract_facts(feed_item_sensitive, repo)
    assert facts == []


def test_single_entity_returns_empty(repo, feed_item_single_entity) -> None:
    """그래프에서 2개 이상 엔티티가 매칭되지 않으면 추출하지 않는다."""
    facts = extract_facts(feed_item_single_entity, repo)
    assert facts == []


def test_extract_fact_from_title(repo, feed_item_bts_award) -> None:
    """LLM이 유효한 사실을 반환하면 ExtractedFact가 생성된다."""
    # repo에는 "아티스트 A"(wd:Q1), "그룹 G"(wd:Q2) 등이 있음 (conftest)
    item = FeedItem(
        title="아티스트 A 그룹 G 소속 확인",
        url="https://news.example.com/member",
        published=date(2024, 1, 1),
        feed_name="테스트",
    )
    llm_response = json.dumps({
        "facts": [{"subject_id": "wd:Q1", "predicate": "memberOf", "object_id": "wd:Q2"}]
    })
    mock_result = LLMResult(ok=True, text=llm_response, model="test", error=None)

    with patch("veristar.ingest.news.extractor.chat", return_value=mock_result):
        facts = extract_facts(item, repo)

    assert len(facts) == 1
    assert facts[0].subject_id == "wd:Q1"
    assert facts[0].predicate == "memberOf"
    assert facts[0].object_id == "wd:Q2"
    assert facts[0].article_url == "https://news.example.com/member"


def test_invalid_predicate_filtered(repo) -> None:
    item = FeedItem(
        title="아티스트 A 그룹 G 관련",
        url="https://news.example.com/x",
        published=date(2024, 1, 1),
        feed_name="테스트",
    )
    llm_response = json.dumps({
        "facts": [{"subject_id": "wd:Q1", "predicate": "marriedTo", "object_id": "wd:Q2"}]
    })
    mock_result = LLMResult(ok=True, text=llm_response, model="test", error=None)

    with patch("veristar.ingest.news.extractor.chat", return_value=mock_result):
        facts = extract_facts(item, repo)

    assert facts == []  # 화이트리스트에 없는 predicate는 버린다


def test_unknown_entity_filtered(repo) -> None:
    item = FeedItem(
        title="아티스트 A 그룹 G 활동",
        url="https://news.example.com/y",
        published=date(2024, 1, 1),
        feed_name="테스트",
    )
    llm_response = json.dumps({
        "facts": [{"subject_id": "wd:Q1", "predicate": "memberOf", "object_id": "wd:Q9999"}]
    })
    mock_result = LLMResult(ok=True, text=llm_response, model="test", error=None)

    with patch("veristar.ingest.news.extractor.chat", return_value=mock_result):
        facts = extract_facts(item, repo)

    assert facts == []  # object가 그래프에 없으면 버린다


def test_llm_failure_returns_empty(repo) -> None:
    item = FeedItem(
        title="아티스트 A 그룹 G 뉴스",
        url="https://news.example.com/z",
        published=date(2024, 1, 1),
        feed_name="테스트",
    )
    mock_result = LLMResult(ok=False, text="", model="test", error="connection error")

    with patch("veristar.ingest.news.extractor.chat", return_value=mock_result):
        facts = extract_facts(item, repo)

    assert facts == []


def test_llm_invalid_json_returns_empty(repo) -> None:
    item = FeedItem(
        title="아티스트 A 그룹 G 뉴스",
        url="https://news.example.com/w",
        published=date(2024, 1, 1),
        feed_name="테스트",
    )
    mock_result = LLMResult(ok=True, text="이건 JSON이 아님", model="test", error=None)

    with patch("veristar.ingest.news.extractor.chat", return_value=mock_result):
        facts = extract_facts(item, repo)

    assert facts == []
