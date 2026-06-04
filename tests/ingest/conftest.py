"""Wikidata 수집기 테스트용 합성 픽스처 (실제 QID 정확성에 의존하지 않음)."""

from __future__ import annotations

from typing import Any

import pytest

from veristar.ingest.wikidata.mapping import WikidataMapping
from veristar.ontology.enums import EntityType

#: 합성 타입 매핑 — 픽스처가 쓰는 QID만 정의해 실제 Wikidata QID와 분리.
TEST_MAPPING = WikidataMapping(
    type_by_qid={
        "Q5": EntityType.PERSON,
        "Q_GROUP": EntityType.GROUP,
        "Q_ORG": EntityType.ORGANIZATION,
    }
)

_REF = [{"hash": "h", "snaks": {"P854": [{"snaktype": "value", "property": "P854"}]}}]


def claim_entity(
    prop: str,
    qid: str,
    *,
    with_ref: bool = True,
    start: str | None = None,
    rank: str = "normal",
) -> dict[str, Any]:
    claim: dict[str, Any] = {
        "mainsnak": {
            "snaktype": "value",
            "property": prop,
            "datavalue": {
                "value": {"entity-type": "item", "id": qid, "numeric-id": 0},
                "type": "wikibase-entityid",
            },
        },
        "type": "statement",
        "rank": rank,
    }
    if with_ref:
        claim["references"] = _REF
    if start is not None:
        claim["qualifiers"] = {
            "P580": [
                {
                    "snaktype": "value",
                    "property": "P580",
                    "datavalue": {"value": {"time": start, "precision": 11}, "type": "time"},
                }
            ]
        }
    return claim


def claim_award(
    qid: str, *, point_in_time: str, category: str, with_ref: bool = True
) -> dict[str, Any]:
    """수상 claim: P585(시점)·P1810(부문) 한정자 포함. P580은 없음(수상은 단발 사건)."""
    claim: dict[str, Any] = {
        "mainsnak": {
            "snaktype": "value",
            "property": "P166",
            "datavalue": {
                "value": {"entity-type": "item", "id": qid, "numeric-id": 0},
                "type": "wikibase-entityid",
            },
        },
        "type": "statement",
        "rank": "normal",
        "qualifiers": {
            "P585": [
                {
                    "snaktype": "value",
                    "property": "P585",
                    "datavalue": {
                        "value": {"time": point_in_time, "precision": 11},
                        "type": "time",
                    },
                }
            ],
            "P1810": [
                {
                    "snaktype": "value",
                    "property": "P1810",
                    "datavalue": {"value": category, "type": "string"},
                }
            ],
        },
    }
    if with_ref:
        claim["references"] = _REF
    return claim


def claim_time(prop: str, time_str: str) -> dict[str, Any]:
    return {
        "mainsnak": {
            "snaktype": "value",
            "property": prop,
            "datavalue": {"value": {"time": time_str, "precision": 11}, "type": "time"},
        },
        "type": "statement",
        "rank": "normal",
    }


@pytest.fixture
def person_item() -> dict[str, Any]:
    """사람 Q1: 그룹 QGRP 소속(reference O, 시작일 O), 무출처 멤버십, 배우자(민감)."""
    return {
        "id": "Q1",
        "labels": {"ko": {"language": "ko", "value": "아티스트 A"}},
        "aliases": {"en": [{"language": "en", "value": "A"}]},
        "claims": {
            "P31": [claim_entity("P31", "Q5")],
            "P569": [claim_time("P569", "+1997-03-30T00:00:00Z")],
            "P106": [claim_entity("P106", "Q177220")],  # occupation
            "P27": [claim_entity("P27", "Q884")],  # nationality
            "P463": [
                claim_entity("P463", "QGRP", with_ref=True, start="+2016-02-23T00:00:00Z"),
                claim_entity("P463", "QGRP2", with_ref=False),  # 무출처 → skip
            ],
            "P26": [claim_entity("P26", "Q999", with_ref=True)],  # 배우자 → 매핑 금지
        },
    }


@pytest.fixture
def group_item() -> dict[str, Any]:
    """그룹 QGRP: 데뷔일 O, has-part(P527)로 멤버 Q1 보유(역방향 매핑 대상)."""
    return {
        "id": "QGRP",
        "labels": {"ko": {"language": "ko", "value": "그룹 G"}},
        "claims": {
            "P31": [claim_entity("P31", "Q_GROUP")],
            "P571": [claim_time("P571", "+2016-02-23T00:00:00Z")],
            "P527": [claim_entity("P527", "Q1", with_ref=True)],  # 그룹→멤버 (역방향)
        },
    }


@pytest.fixture
def award_winner_item() -> dict[str, Any]:
    """그룹 QW: 같은 상(QAWARD)을 다른 해·부문으로 두 번 수상 (P585·P1810으로 구분)."""
    return {
        "id": "QW",
        "labels": {"ko": {"language": "ko", "value": "그룹 W"}},
        "claims": {
            "P31": [claim_entity("P31", "Q_GROUP")],
            "P166": [
                claim_award("QAWARD", point_in_time="+2019-01-06T00:00:00Z", category="신인상"),
                claim_award("QAWARD", point_in_time="+2022-01-08T00:00:00Z", category="본상"),
            ],
        },
    }


@pytest.fixture
def unknown_item() -> dict[str, Any]:
    """타입 판정 불가(P31 값이 매핑에 없음)."""
    return {
        "id": "Q_X",
        "labels": {"en": {"language": "en", "value": "X"}},
        "claims": {"P31": [claim_entity("P31", "Q_UNMAPPED")]},
    }
