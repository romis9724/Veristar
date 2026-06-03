"""API 테스트용 TestClient (픽스처 저장소 주입, 네트워크 0)."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from veristar.api import create_app
from veristar.graph import InMemoryGraphRepository
from veristar.ontology import Group, Person, Source
from veristar.ontology.enums import Grade, Predicate, SourceType, Status
from veristar.ontology.graph import GraphDocument
from veristar.ontology.models import Statement


@pytest.fixture
def client() -> TestClient:
    person = Person(
        id="wd:Q1", name="아티스트 A", aliases=["Artist A"], created_at=datetime(2026, 1, 1)
    )
    group = Group(id="wd:Q2", name="그룹 G", created_at=datetime(2026, 1, 1))
    src = Source(
        id="src1",
        source_type=SourceType.WIKIDATA_VERIFIED,
        publisher="Wikidata",
        url="https://www.wikidata.org/wiki/Q1",
        title="A",
        license="CC0",
    )
    member = Statement(
        id="s1",
        subject="wd:Q1",
        predicate=Predicate.MEMBER_OF,
        object="wd:Q2",
        grade=Grade.OFFICIAL,
        status=Status.ACTIVE,
        sources=["src1"],
        valid_from="2016-02-23",
    )
    doc = GraphDocument(entities=[person, group], sources=[src], statements=[member])
    app = create_app(InMemoryGraphRepository(doc))
    return TestClient(app)
