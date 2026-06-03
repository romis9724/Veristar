"""시드 오케스트레이션 테스트 — FakeWikidataClient (네트워크 없음)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from veristar.ingest.wikidata.seed import build_seed, write_seed
from veristar.ontology import load_graph
from veristar.ontology.enums import EntityType, Predicate

from .conftest import TEST_MAPPING

RETRIEVED = datetime(2026, 6, 4)


class FakeWikidataClient:
    """미리 준비한 dict로 응답. 없는 QID는 KeyError."""

    def __init__(self, items: dict[str, dict[str, Any]]) -> None:
        self._items = items
        self.fetched: list[str] = []

    def fetch_entity(self, qid: str) -> dict[str, Any]:
        self.fetched.append(qid)
        return self._items[qid]


def _seed(items: dict[str, Any], roots: list[str], **kw: Any):
    client = FakeWikidataClient(items)
    doc = build_seed(client, roots, retrieved_at=RETRIEVED, mapping=TEST_MAPPING, **kw)
    return client, doc


def test_expands_from_root_and_validates(
    person_item: dict[str, Any], group_item: dict[str, Any]
) -> None:
    _, doc = _seed({"Q1": person_item, "QGRP": group_item}, ["Q1"])
    ids = {e.id for e in doc.entities}
    assert ids == {"wd:Q1", "wd:QGRP"}  # 루트에서 멤버십 따라 그룹까지 확장
    assert any(s.predicate is Predicate.MEMBER_OF for s in doc.statements)
    assert doc.validate_cross_references() == []  # 산출물은 M1 검증 통과


def test_group_node_type(person_item: dict[str, Any], group_item: dict[str, Any]) -> None:
    _, doc = _seed({"Q1": person_item, "QGRP": group_item}, ["Q1"])
    group = next(e for e in doc.entities if e.id == "wd:QGRP")
    assert group.type is EntityType.GROUP


def test_max_entities_limits_expansion(
    person_item: dict[str, Any], group_item: dict[str, Any]
) -> None:
    client, doc = _seed({"Q1": person_item, "QGRP": group_item}, ["Q1"], max_entities=1)
    assert len(doc.entities) == 1
    assert client.fetched == ["Q1"]


def test_missing_entity_is_skipped_not_fatal(person_item: dict[str, Any]) -> None:
    # QGRP를 제공하지 않아 fetch가 KeyError → 건너뛰고 Q1만 남는다
    _, doc = _seed({"Q1": person_item}, ["Q1"])
    assert {e.id for e in doc.entities} == {"wd:Q1"}


def test_write_seed_roundtrips_through_load_graph(
    tmp_path: Path, person_item: dict[str, Any], group_item: dict[str, Any]
) -> None:
    _, doc = _seed({"Q1": person_item, "QGRP": group_item}, ["Q1"])
    out = write_seed(doc, tmp_path / "seed.json")
    assert out.exists()
    reloaded = load_graph(out)  # M1 전체 validation 통과해야 함
    assert {e.id for e in reloaded.entities} == {"wd:Q1", "wd:QGRP"}


def test_unknown_root_yields_empty_graph(unknown_item: dict[str, Any]) -> None:
    _, doc = _seed({"Q_X": unknown_item}, ["Q_X"])
    assert doc.entities == []
    assert doc.statements == []
