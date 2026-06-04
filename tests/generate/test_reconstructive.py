"""재구성형 생성 테스트 — OFFICIAL 사실만 입력, 추론 없음."""

from __future__ import annotations

from datetime import datetime

from veristar.generate import generate_summary, generate_timeline_text
from veristar.graph import InMemoryGraphRepository
from veristar.ontology.enums import Grade, Predicate, SourceType, Status
from veristar.ontology.graph import GraphDocument
from veristar.ontology.models import Award, Group, Person, Source, Statement


def _repo() -> InMemoryGraphRepository:
    g = Group(id="wd:QG", name="그룹 G", created_at=datetime(2026, 1, 1))
    p = Person(id="wd:QP", name="아티스트 A", created_at=datetime(2026, 1, 1))
    a = Award(id="wd:QA", name="올해의 상", created_at=datetime(2026, 1, 1))
    src = Source(
        id="s1",
        source_type=SourceType.WIKIDATA_VERIFIED,
        publisher="Wikidata",
        url="https://www.wikidata.org/wiki/QG",
        title="G",
        license="CC0",
    )
    stmts = [
        Statement(
            id="sm1",
            subject="wd:QP",
            predicate=Predicate.MEMBER_OF,
            object="wd:QG",
            grade=Grade.OFFICIAL,
            status=Status.ACTIVE,
            sources=["s1"],
            valid_from="2016-01-01",
        ),
        Statement(
            id="sm2",
            subject="wd:QG",
            predicate=Predicate.WON_AWARD,
            object="wd:QA",
            grade=Grade.OFFICIAL,
            status=Status.ACTIVE,
            sources=["s1"],
            valid_from="2021-01-09",
            qualifier="본상",
        ),
        Statement(
            id="sm3",
            subject="wd:QG",
            predicate=Predicate.WON_AWARD,
            object="wd:QA",
            grade=Grade.REPORTED,  # REPORTED → 생성 제외
            status=Status.ACTIVE,
            sources=["s1"],
        ),
        Statement(
            id="sm4",
            subject="wd:QG",
            predicate=Predicate.WON_AWARD,
            object="wd:QA",
            grade=Grade.OFFICIAL,
            status=Status.ACTIVE,
            sources=["s1"],
            sensitive=True,  # 민감 → 생성 제외
        ),
    ]
    doc = GraphDocument(entities=[g, p, a], sources=[src], statements=stmts)
    return InMemoryGraphRepository(doc)


def test_timeline_only_official_nonsensitive() -> None:
    text = generate_timeline_text(_repo(), "wd:QG")
    assert "올해의 상" in text
    assert "본상" in text
    # REPORTED·민감은 제외
    assert text.count("올해의 상") == 1


def test_timeline_sorted_by_year() -> None:
    text = generate_timeline_text(_repo(), "wd:QG")
    assert "2021" in text


def test_summary_includes_award_and_source_count() -> None:
    result = generate_summary(_repo(), "wd:QG")
    assert result is not None
    assert "그룹 G" in result.entity_name
    assert "올해의 상" in result.summary_text or "올해의 상" in result.timeline_text
    assert result.statement_count == 2  # sm2(수상) + sm1(멤버십, in 방향)


def test_summary_none_for_missing_entity() -> None:
    assert generate_summary(_repo(), "wd:QNOTEXIST") is None


# Q&A(LLM) 테스트는 tests/generate/test_qa.py 로 이동 (Ollama qwen3 기반).
