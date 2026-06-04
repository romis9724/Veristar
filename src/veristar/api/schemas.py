"""API 응답 스키마 + 도메인→DTO 변환.

일관 엔벨로프: { "data": ..., "error": null } (patterns).
모든 statement 응답에 출처(등급 포함)를 평탄화해 싣는다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel

from veristar.graph.queries import EntityDetail, StatementView
from veristar.ontology.models import Entity, Source


class SourceOut(BaseModel):
    id: str
    source_type: str
    publisher: str
    url: str
    title: str
    license: str | None = None


class EntityOut(BaseModel):
    id: str
    type: str
    name: str
    aliases: list[str]


class StatementOut(BaseModel):
    id: str
    predicate: str
    direction: str
    grade: str
    status: str
    other_id: str
    other_name: str | None
    other_type: str | None
    qualifier: str | None
    valid_from: date | None
    valid_to: date | None
    sources: list[SourceOut]


class EntityDetailOut(BaseModel):
    entity: EntityOut
    outgoing_count: int
    incoming_count: int


def source_to_out(src: Source) -> SourceOut:
    return SourceOut(
        id=src.id,
        source_type=src.source_type.value,
        publisher=src.publisher,
        url=src.url,
        title=src.title,
        license=src.license,
    )


def entity_to_out(entity: Entity) -> EntityOut:
    return EntityOut(
        id=entity.id,
        type=entity.type.value,
        name=entity.name,
        aliases=list(entity.aliases),
    )


def view_to_out(view: StatementView) -> StatementOut:
    stmt = view.statement
    return StatementOut(
        id=stmt.id,
        predicate=stmt.predicate.value,
        direction=view.direction,
        grade=stmt.grade.value,
        status=stmt.status.value,
        other_id=view.other_id,
        other_name=view.other.name if view.other else None,
        other_type=view.other.type.value if view.other else None,
        qualifier=stmt.qualifier,
        valid_from=stmt.valid_from,
        valid_to=stmt.valid_to,
        sources=[source_to_out(s) for s in view.sources],
    )


def detail_to_out(detail: EntityDetail) -> EntityDetailOut:
    return EntityDetailOut(
        entity=entity_to_out(detail.entity),
        outgoing_count=detail.outgoing_count,
        incoming_count=detail.incoming_count,
    )


def ok(data: Any) -> dict[str, Any]:
    return {"data": data, "error": None}
