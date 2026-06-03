"""교차참조 validation 테스트 — 스키마 §5 규칙 2·3."""

from __future__ import annotations

from datetime import datetime

from veristar.ontology import (
    GraphDocument,
    Person,
    Source,
    Statement,
)
from veristar.ontology.enums import Grade, Predicate


def _person() -> Person:
    return Person(id="p", name="X", created_at=datetime(2026, 1, 1))


def _stmt(grade: Grade, sources: list[str]) -> Statement:
    return Statement(
        id="stmt_1",
        subject="p",
        predicate=Predicate.MEMBER_OF,
        object="g",
        grade=grade,
        sources=sources,
    )


# --- 규칙 2: 참조된 source id가 실재 ---


def test_rule2_missing_source_reference_flagged(official_source: Source) -> None:
    doc = GraphDocument(
        entities=[_person()],
        sources=[official_source],
        statements=[_stmt(Grade.OFFICIAL, ["does_not_exist"])],
    )
    violations = doc.validate_cross_references()
    assert any(v.rule == 2 and v.statement_id == "stmt_1" for v in violations)


def test_rule2_existing_source_reference_ok(official_source: Source) -> None:
    doc = GraphDocument(
        entities=[_person()],
        sources=[official_source],
        statements=[_stmt(Grade.OFFICIAL, [official_source.id])],
    )
    assert [v for v in doc.validate_cross_references() if v.rule == 2] == []


# --- 규칙 3: grade가 출처 유형이 받쳐주는 등급과 모순되지 않음 ---


def test_rule3_official_grade_on_press_source_flagged(press_source: Source) -> None:
    # PRESS는 REPORTED가 상한 → OFFICIAL 주장은 위반
    doc = GraphDocument(
        entities=[_person()],
        sources=[press_source],
        statements=[_stmt(Grade.OFFICIAL, [press_source.id])],
    )
    violations = doc.validate_cross_references()
    assert any(v.rule == 3 for v in violations)


def test_rule3_reported_grade_on_press_source_ok(press_source: Source) -> None:
    doc = GraphDocument(
        entities=[_person()],
        sources=[press_source],
        statements=[_stmt(Grade.REPORTED, [press_source.id])],
    )
    assert [v for v in doc.validate_cross_references() if v.rule == 3] == []


def test_rule3_conservative_downgrade_allowed(official_source: Source) -> None:
    # OFFICIAL 출처에 RUMOR 부여(보수적 하향)는 허용
    doc = GraphDocument(
        entities=[_person()],
        sources=[official_source],
        statements=[_stmt(Grade.RUMOR, [official_source.id])],
    )
    assert [v for v in doc.validate_cross_references() if v.rule == 3] == []


def test_rule3_best_of_multiple_sources_justifies_grade(
    official_source: Source, press_source: Source
) -> None:
    # 여러 출처 중 하나라도 OFFICIAL을 받쳐주면 OFFICIAL 허용
    doc = GraphDocument(
        entities=[_person()],
        sources=[official_source, press_source],
        statements=[_stmt(Grade.OFFICIAL, [press_source.id, official_source.id])],
    )
    assert [v for v in doc.validate_cross_references() if v.rule == 3] == []
