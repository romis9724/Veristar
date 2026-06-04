"""조회 연산 — search·detail·statements·timeline·neighbors.

저장소(repository) 위에서 동작하며, 각 statement에 **출처(등급 포함)** 를 부착한다.
이것이 Veristar 탐색의 차별점이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from veristar.ontology.models import Entity, Source, Statement

from .filters import StatementFilter
from .repository import GraphRepository


@dataclass(frozen=True)
class StatementView:
    """한 statement를 엔티티 관점에서 본 것 (방향·상대·출처 포함)."""

    statement: Statement
    direction: str  # "out"(엔티티가 subject) | "in"(엔티티가 object)
    other_id: str  # 상대 엔티티 id (out이면 object, in이면 subject)
    other: Entity | None  # 그래프에 있으면 엔티티, 없으면 None(리터럴/미수집)
    sources: list[Source]


@dataclass(frozen=True)
class EntityDetail:
    entity: Entity
    outgoing_count: int
    incoming_count: int


def search(repo: GraphRepository, query: str, limit: int = 20) -> list[Entity]:
    return repo.search_entities(query, limit)


def entity_detail(repo: GraphRepository, entity_id: str) -> EntityDetail | None:
    entity = repo.get_entity(entity_id)
    if entity is None:
        return None
    return EntityDetail(
        entity=entity,
        outgoing_count=len(repo.outgoing(entity_id)),
        incoming_count=len(repo.incoming(entity_id)),
    )


def _view(repo: GraphRepository, entity_id: str, stmt: Statement) -> StatementView:
    if stmt.subject == entity_id:
        direction, other_id = "out", stmt.object
    else:
        direction, other_id = "in", stmt.subject
    sources = [s for sid in stmt.sources if (s := repo.get_source(sid)) is not None]
    return StatementView(
        statement=stmt,
        direction=direction,
        other_id=other_id,
        other=repo.get_entity(other_id),
        sources=sources,
    )


def statements_for(
    repo: GraphRepository,
    entity_id: str,
    filt: StatementFilter | None = None,
) -> list[StatementView]:
    filt = filt or StatementFilter()
    return [_view(repo, entity_id, s) for s in repo.statements_of(entity_id) if filt.matches(s)]


_FAR_FUTURE = date.max


def timeline(
    repo: GraphRepository,
    entity_id: str,
    filt: StatementFilter | None = None,
) -> list[StatementView]:
    """valid_from 기준 시간순. valid_from 없는 항목은 맨 뒤."""
    views = statements_for(repo, entity_id, filt)
    return sorted(views, key=lambda v: v.statement.valid_from or _FAR_FUTURE)


def neighbors(
    repo: GraphRepository,
    entity_id: str,
    filt: StatementFilter | None = None,
) -> list[StatementView]:
    """인접 엔티티 (그래프에 실재하는 상대만, 상대 id 기준 중복 제거)."""
    seen: set[str] = set()
    out: list[StatementView] = []
    for view in statements_for(repo, entity_id, filt):
        if view.other is not None and view.other_id not in seen:
            seen.add(view.other_id)
            out.append(view)
    return out
