"""생성 입력 게이트 테스트 — 스키마 §5 규칙 5."""

from __future__ import annotations

from datetime import datetime

from veristar.ontology import GraphDocument, Person, Source, Statement, official_nonsensitive
from veristar.ontology.enums import Grade, Predicate, SourceType, Status


def _doc(statements: list[Statement]) -> GraphDocument:
    return GraphDocument(
        entities=[Person(id="p", name="X", created_at=datetime(2026, 1, 1))],
        sources=[
            Source(
                id="s",
                source_type=SourceType.OFFICIAL_ANNOUNCEMENT,
                publisher="pub",
                url="https://example.com/1",
                title="t",
            )
        ],
        statements=statements,
    )


def _stmt(
    sid: str,
    grade: Grade,
    *,
    sensitive: bool = False,
    status: Status = Status.ACTIVE,
) -> Statement:
    return Statement(
        id=sid,
        subject="p",
        predicate=Predicate.MEMBER_OF,
        object="g",
        grade=grade,
        status=status,
        sources=["s"],
        sensitive=sensitive,
    )


def test_official_nonsensitive_active_included() -> None:
    doc = _doc([_stmt("ok", Grade.OFFICIAL)])
    assert [s.id for s in official_nonsensitive(doc)] == ["ok"]


def test_reported_and_rumor_excluded() -> None:
    doc = _doc([_stmt("r", Grade.REPORTED), _stmt("u", Grade.RUMOR)])
    assert official_nonsensitive(doc) == []


def test_sensitive_official_excluded() -> None:
    doc = _doc([_stmt("sens", Grade.OFFICIAL, sensitive=True)])
    assert official_nonsensitive(doc) == []


def test_superseded_and_retracted_excluded() -> None:
    doc = _doc(
        [
            _stmt("sup", Grade.OFFICIAL, status=Status.SUPERSEDED),
            _stmt("ret", Grade.OFFICIAL, status=Status.RETRACTED),
        ]
    )
    assert official_nonsensitive(doc) == []


def test_mixed_only_official_active_nonsensitive_kept() -> None:
    doc = _doc(
        [
            _stmt("keep", Grade.OFFICIAL),
            _stmt("drop_reported", Grade.REPORTED),
            _stmt("drop_sensitive", Grade.OFFICIAL, sensitive=True),
            _stmt("drop_superseded", Grade.OFFICIAL, status=Status.SUPERSEDED),
        ]
    )
    assert [s.id for s in official_nonsensitive(doc)] == ["keep"]
