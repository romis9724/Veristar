"""Wikidata 엔티티 JSON → Veristar 타입 (순수 매핑, 네트워크 없음).

입력: Special:EntityData 의 단일 아이템 dict (`response["entities"][qid]`).
출력: MappedRecords(entity, statements, sources) — M1 validation을 통과하도록 만든다.

원칙(service-design §4.1):
- reference 없는 claim은 기본 skip(`require_reference=True`).
- 화이트리스트 밖 속성은 매핑하지 않음(민감 필터).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from veristar.ontology.enums import EntityType, Grade, SourceType, Status
from veristar.ontology.models import (
    Award,
    Entity,
    Event,
    Group,
    Organization,
    Person,
    Source,
    Statement,
    Work,
)

from .mapping import DEFAULT_MAPPING, WikidataMapping, qid_to_id

_ENTITY_CTOR: dict[EntityType, type] = {
    EntityType.PERSON: Person,
    EntityType.GROUP: Group,
    EntityType.ORGANIZATION: Organization,
    EntityType.WORK: Work,
    EntityType.EVENT: Event,
    EntityType.AWARD: Award,
}


@dataclass(frozen=True)
class MappedRecords:
    """한 Wikidata 아이템에서 뽑은 결과."""

    entity: Entity
    statements: list[Statement]
    sources: list[Source]


# --- 저수준 파서 ---


def _label(item: dict[str, Any], langs: tuple[str, ...] = ("ko", "en")) -> str | None:
    labels = item.get("labels", {})
    for lang in langs:
        if lang in labels:
            return str(labels[lang]["value"])
    return None


def _aliases(item: dict[str, Any], langs: tuple[str, ...] = ("ko", "en")) -> list[str]:
    out: list[str] = []
    aliases = item.get("aliases", {})
    for lang in langs:
        for entry in aliases.get(lang, []):
            out.append(str(entry["value"]))
    return out


def _claims(item: dict[str, Any], prop: str) -> list[dict[str, Any]]:
    return [c for c in item.get("claims", {}).get(prop, []) if c.get("rank") != "deprecated"]


def _main_value(claim: dict[str, Any]) -> Any | None:
    snak = claim.get("mainsnak", {})
    if snak.get("snaktype") != "value":
        return None
    return snak.get("datavalue", {}).get("value")


def _entity_qid(value: Any) -> str | None:
    if isinstance(value, dict) and value.get("entity-type") == "item":
        return str(value["id"])
    return None


def _has_reference(claim: dict[str, Any]) -> bool:
    return bool(claim.get("references"))


def _parse_time(value: Any) -> tuple[int | None, date | None]:
    """Wikidata time value → (year, date). 월/일 00은 01로 보정. BCE/이상치는 (None, None)."""
    if not isinstance(value, dict):
        return None, None
    raw = str(value.get("time", ""))
    if not raw.startswith("+"):  # 음수(BCE) 등은 다루지 않음
        return None, None
    body = raw[1:11]  # YYYY-MM-DD
    parts = body.split("-")
    if len(parts) != 3:
        return None, None
    year_s, month_s, day_s = parts
    try:
        year = int(year_s)
    except ValueError:
        return None, None
    month = max(int(month_s), 1)
    day = max(int(day_s), 1)
    try:
        return year, date(year, month, day)
    except ValueError:
        return year, None


def _qualifier_date(claim: dict[str, Any], prop: str) -> date | None:
    for q in claim.get("qualifiers", {}).get(prop, []):
        if q.get("snaktype") == "value":
            _, d = _parse_time(q.get("datavalue", {}).get("value"))
            return d
    return None


# --- 엔티티 타입·속성 ---


def _resolve_type(item: dict[str, Any], m: WikidataMapping) -> EntityType | None:
    for claim in _claims(item, m.instance_of):
        qid = _entity_qid(_main_value(claim))
        if qid and qid in m.type_by_qid:
            return m.type_by_qid[qid]
    return None


def _entity_attrs(item: dict[str, Any], etype: EntityType, m: WikidataMapping) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    if etype is EntityType.PERSON:
        for claim in _claims(item, m.birth_date_prop):
            year, _ = _parse_time(_main_value(claim))
            if year is not None:
                attrs["birth_year"] = year
                break
        occ = [
            qid_to_id(qid)
            for claim in _claims(item, m.occupation_prop)
            if (qid := _entity_qid(_main_value(claim)))
        ]
        if occ:
            attrs["occupation"] = occ
        for claim in _claims(item, m.nationality_prop):
            qid = _entity_qid(_main_value(claim))
            if qid:
                attrs["nationality"] = qid_to_id(qid)
                break
    elif etype is EntityType.GROUP:
        for claim in _claims(item, m.inception_prop):
            _, d = _parse_time(_main_value(claim))
            if d is not None:
                attrs["debut_date"] = d
                break
    elif etype is EntityType.WORK:
        for claim in _claims(item, m.publication_prop):
            _, d = _parse_time(_main_value(claim))
            if d is not None:
                attrs["release_date"] = d
                break
    return attrs


# --- 공개 진입점 ---


def map_item(
    item: dict[str, Any],
    *,
    retrieved_at: datetime,
    mapping: WikidataMapping = DEFAULT_MAPPING,
    require_reference: bool = True,
) -> MappedRecords | None:
    """단일 Wikidata 아이템 → MappedRecords. 타입 판정 불가면 None."""
    qid = str(item["id"])
    etype = _resolve_type(item, mapping)
    if etype is None:
        return None

    name = _label(item) or qid
    ctor = _ENTITY_CTOR[etype]
    entity: Entity = ctor(
        id=qid_to_id(qid),
        name=name,
        aliases=_aliases(item),
        created_at=retrieved_at,
        **_entity_attrs(item, etype, mapping),
    )

    source = Source(
        id=f"src_wd_{qid}",
        source_type=SourceType.WIKIDATA_VERIFIED,
        publisher="Wikidata",
        url=f"https://www.wikidata.org/wiki/{qid}",
        title=name,
        retrieved_at=retrieved_at.date(),
        license="CC0",
    )

    statements: list[Statement] = []
    for prop, predicate in mapping.statement_props.items():
        for idx, claim in enumerate(_claims(item, prop)):
            if require_reference and not _has_reference(claim):
                continue
            object_qid = _entity_qid(_main_value(claim))
            if object_qid is None:
                continue
            statements.append(
                Statement(
                    id=f"stmt_wd_{qid}_{prop}_{object_qid}_{idx}",
                    subject=qid_to_id(qid),
                    predicate=predicate,
                    object=qid_to_id(object_qid),
                    grade=Grade.OFFICIAL,
                    status=Status.ACTIVE,
                    sources=[source.id],
                    valid_from=_qualifier_date(claim, mapping.start_qualifier),
                    valid_to=_qualifier_date(claim, mapping.end_qualifier),
                    sensitive=False,
                )
            )

    sources = [source] if statements else []
    return MappedRecords(entity=entity, statements=statements, sources=sources)
