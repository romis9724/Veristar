"""온톨로지 테스트 공용 픽스처."""

from __future__ import annotations

from datetime import datetime

import pytest

from veristar.ontology import Person, Source, Statement
from veristar.ontology.enums import Grade, Predicate, SourceType, Status


@pytest.fixture
def official_source() -> Source:
    """OFFICIAL 등급을 받쳐주는 출처."""
    return Source(
        id="src_official",
        source_type=SourceType.OFFICIAL_ANNOUNCEMENT,
        publisher="소속사 공식",
        url="https://example.com/official/1",
        title="공식 발표",
    )


@pytest.fixture
def press_source() -> Source:
    """REPORTED가 상한인 언론 출처."""
    return Source(
        id="src_press",
        source_type=SourceType.PRESS,
        publisher="언론사",
        url="https://example.com/press/1",
        title="보도",
    )


@pytest.fixture
def person() -> Person:
    return Person(id="person_x", name="아티스트 X", created_at=datetime(2026, 1, 1))


@pytest.fixture
def valid_statement() -> Statement:
    """규칙 1·4·6을 모두 만족하는 기본 statement."""
    return Statement(
        id="stmt_x",
        subject="person_x",
        predicate=Predicate.MEMBER_OF,
        object="group_x",
        grade=Grade.OFFICIAL,
        status=Status.ACTIVE,
        sources=["src_official"],
        valid_from="2016-02-23",
        sensitive=False,
    )
