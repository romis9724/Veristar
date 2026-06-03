"""모델 레벨 validation 테스트 — 스키마 §5 규칙 1·4·6."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from veristar.ontology import Person, Statement
from veristar.ontology.enums import EntityType, Grade, Predicate


def test_valid_statement_passes(valid_statement: Statement) -> None:
    assert valid_statement.predicate is Predicate.MEMBER_OF
    assert valid_statement.sources == ["src_official"]


# --- 규칙 1: Statement는 source ≥ 1개 ---


def test_rule1_statement_without_source_rejected() -> None:
    with pytest.raises(ValidationError):
        Statement(
            id="s",
            subject="a",
            predicate=Predicate.MEMBER_OF,
            object="b",
            grade=Grade.OFFICIAL,
            sources=[],  # 위반
        )


def test_rule1_statement_with_one_source_ok() -> None:
    stmt = Statement(
        id="s",
        subject="a",
        predicate=Predicate.MEMBER_OF,
        object="b",
        grade=Grade.OFFICIAL,
        sources=["src_1"],
    )
    assert len(stmt.sources) == 1


# --- 규칙 4: predicate는 화이트리스트 ---


def test_rule4_unknown_predicate_rejected() -> None:
    with pytest.raises(ValidationError):
        Statement(
            id="s",
            subject="a",
            predicate="datedSecretly",  # 어휘 밖 — 거부
            object="b",
            grade=Grade.OFFICIAL,
            sources=["src_1"],
        )


def test_rule4_all_whitelisted_predicates_accepted() -> None:
    for pred in Predicate:
        stmt = Statement(
            id="s",
            subject="a",
            predicate=pred,
            object="b",
            grade=Grade.OFFICIAL,
            sources=["src_1"],
        )
        assert stmt.predicate is pred


# --- 규칙 6: valid_to 있으면 valid_from <= valid_to ---


def test_rule6_valid_from_after_valid_to_rejected() -> None:
    with pytest.raises(ValidationError):
        Statement(
            id="s",
            subject="a",
            predicate=Predicate.MEMBER_OF,
            object="b",
            grade=Grade.OFFICIAL,
            sources=["src_1"],
            valid_from="2020-01-01",
            valid_to="2018-01-01",  # 위반: 시작이 종료보다 늦음
        )


def test_rule6_valid_window_in_order_ok() -> None:
    stmt = Statement(
        id="s",
        subject="a",
        predicate=Predicate.MEMBER_OF,
        object="b",
        grade=Grade.OFFICIAL,
        sources=["src_1"],
        valid_from="2018-01-01",
        valid_to="2020-01-01",
    )
    assert stmt.valid_to is not None


def test_rule6_open_ended_window_ok() -> None:
    # valid_to 없음 → 현재 유효, 검사 통과
    stmt = Statement(
        id="s",
        subject="a",
        predicate=Predicate.MEMBER_OF,
        object="b",
        grade=Grade.OFFICIAL,
        sources=["src_1"],
        valid_from="2018-01-01",
    )
    assert stmt.valid_to is None


# --- 엔티티 discriminated union ---


def test_person_discriminated_type() -> None:
    p = Person.model_validate({"id": "p1", "name": "X", "created_at": "2026-01-01T00:00:00Z"})
    assert p.type is EntityType.PERSON


def test_serialization_round_trip(valid_statement: Statement) -> None:
    dumped = valid_statement.model_dump_json()
    restored = Statement.model_validate_json(dumped)
    assert restored == valid_statement
