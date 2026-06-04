"""공유 pytest 픽스처 — 모든 테스트 모듈에서 사용 가능."""

from __future__ import annotations

from datetime import datetime

import pytest

from veristar.graph import InMemoryGraphRepository
from veristar.ontology import Group, Organization, Person, Source, Statement
from veristar.ontology.enums import Grade, Predicate, SourceType, Status
from veristar.ontology.graph import GraphDocument


@pytest.fixture
def repo() -> InMemoryGraphRepository:
    """소규모 합성 그래프 저장소.

    엔티티: wd:Q1(아티스트 A/Person), wd:Q2(그룹 G/Group), wd:Q3(소속사 C/Org)
    관계: Q1→memberOf→Q2(OFFICIAL), Q2→affiliatedWith→Q3(REPORTED)
    """
    person = Person(
        id="wd:Q1", name="아티스트 A", aliases=["Artist A"], created_at=datetime(2026, 1, 1)
    )
    group = Group(id="wd:Q2", name="그룹 G", created_at=datetime(2026, 1, 1))
    org = Organization(id="wd:Q3", name="소속사 C", created_at=datetime(2026, 1, 1))
    src = Source(
        id="src_wd_Q1",
        source_type=SourceType.WIKIDATA_VERIFIED,
        publisher="Wikidata",
        url="https://www.wikidata.org/wiki/Q1",
        title="A",
        license="CC0",
    )
    member = Statement(
        id="s_member",
        subject="wd:Q1",
        predicate=Predicate.MEMBER_OF,
        object="wd:Q2",
        grade=Grade.OFFICIAL,
        status=Status.ACTIVE,
        sources=["src_wd_Q1"],
        valid_from="2016-02-23",
    )
    affil = Statement(
        id="s_affil",
        subject="wd:Q2",
        predicate=Predicate.AFFILIATED_WITH,
        object="wd:Q3",
        grade=Grade.REPORTED,
        status=Status.ACTIVE,
        sources=["src_wd_Q1"],
        valid_from="2018-01-01",
    )
    old = Statement(
        id="s_old",
        subject="wd:Q1",
        predicate=Predicate.MEMBER_OF,
        object="wd:Q9",
        grade=Grade.OFFICIAL,
        status=Status.SUPERSEDED,
        sources=["src_wd_Q1"],
        valid_from="2010-01-01",
        valid_to="2015-01-01",
    )
    doc = GraphDocument(
        entities=[person, group, org],
        sources=[src],
        statements=[member, affil, old],
    )
    return InMemoryGraphRepository(doc)
