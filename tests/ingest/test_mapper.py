"""순수 매퍼 테스트 — Wikidata JSON → Veristar 타입."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from veristar.ingest.wikidata.mapper import map_item
from veristar.ontology.enums import EntityType, Grade, Predicate, SourceType

from .conftest import TEST_MAPPING

RETRIEVED = datetime(2026, 6, 4)


def _map(item: dict[str, Any], **kw: Any):
    return map_item(item, retrieved_at=RETRIEVED, mapping=TEST_MAPPING, **kw)


def test_person_type_and_attrs(person_item: dict[str, Any]) -> None:
    rec = _map(person_item)
    assert rec is not None
    assert rec.entity.type is EntityType.PERSON
    assert rec.entity.id == "wd:Q1"
    assert rec.entity.name == "아티스트 A"
    assert rec.entity.aliases == ["A"]
    assert rec.entity.birth_year == 1997
    assert rec.entity.occupation == ["wd:Q177220"]
    assert rec.entity.nationality == "wd:Q884"


def test_member_statement_with_reference_and_qualifier(person_item: dict[str, Any]) -> None:
    rec = _map(person_item)
    assert rec is not None
    members = [s for s in rec.statements if s.predicate is Predicate.MEMBER_OF]
    assert len(members) == 1  # 무출처 QGRP2는 제외됨
    stmt = members[0]
    assert stmt.object == "wd:QGRP"
    assert stmt.valid_from == date(2016, 2, 23)
    assert stmt.grade is Grade.OFFICIAL


def test_unreferenced_claim_skipped_by_default(person_item: dict[str, Any]) -> None:
    rec = _map(person_item)
    assert rec is not None
    assert all(s.object != "wd:QGRP2" for s in rec.statements)


def test_allow_unreferenced_includes_claim(person_item: dict[str, Any]) -> None:
    rec = _map(person_item, require_reference=False)
    assert rec is not None
    assert any(s.object == "wd:QGRP2" for s in rec.statements)


def test_sensitive_property_not_mapped(person_item: dict[str, Any]) -> None:
    # P26(배우자)는 화이트리스트 밖 → 어떤 statement에도 나타나면 안 됨
    rec = _map(person_item)
    assert rec is not None
    assert all(s.object != "wd:Q999" for s in rec.statements)


def test_all_statements_official_and_reference_wikidata_source(
    person_item: dict[str, Any],
) -> None:
    rec = _map(person_item)
    assert rec is not None
    assert len(rec.sources) == 1
    src = rec.sources[0]
    assert src.source_type is SourceType.WIKIDATA_VERIFIED
    assert src.license == "CC0"
    assert all(s.grade is Grade.OFFICIAL for s in rec.statements)
    assert all(s.sources == [src.id] for s in rec.statements)


def test_unknown_type_returns_none(unknown_item: dict[str, Any]) -> None:
    assert _map(unknown_item) is None


def test_group_debut_date(group_item: dict[str, Any]) -> None:
    rec = _map(group_item)
    assert rec is not None
    assert rec.entity.type is EntityType.GROUP
    assert rec.entity.debut_date == date(2016, 2, 23)


def test_has_part_is_expansion_hint_not_statement(group_item: dict[str, Any]) -> None:
    # P527(has part)은 statement를 만들지 않고 확장 힌트로만 쓴다.
    # memberOf 엣지는 멤버 본인의 P463에서 나오므로 그룹은 멤버 statement를 안 만든다.
    rec = _map(group_item)
    assert rec is not None
    assert all(s.predicate is not Predicate.MEMBER_OF for s in rec.statements)
    assert rec.statements == []
    assert rec.sources == []
    assert "Q1" in rec.expand_qids  # 멤버는 확장 대상으로만 잡힘


def test_statement_object_added_to_expand(person_item: dict[str, Any]) -> None:
    # 관계 object(QGRP)는 reference 유무와 무관하게 확장 대상에 포함
    rec = _map(person_item)
    assert rec is not None
    assert "QGRP" in rec.expand_qids
    assert "QGRP2" in rec.expand_qids  # 무출처라 statement는 없지만 발견은 됨
