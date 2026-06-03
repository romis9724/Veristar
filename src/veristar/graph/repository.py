"""그래프 저장소 (파이프라인 [4] + query 기반).

Repository 패턴: 비즈니스/조회 로직은 `GraphRepository` Protocol에 의존하고,
저장 구현(현재 인메모리 JSON, 후일 Neo4j)은 갈아끼울 수 있다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from veristar.ontology.graph import GraphDocument, load_graph
from veristar.ontology.models import Entity, Source, Statement


class GraphRepository(Protocol):
    """그래프 조회 인터페이스 (읽기 전용)."""

    def get_entity(self, entity_id: str) -> Entity | None: ...
    def search_entities(self, query: str, limit: int = 20) -> list[Entity]: ...
    def statements_of(self, entity_id: str) -> list[Statement]: ...
    def get_source(self, source_id: str) -> Source | None: ...
    def stats(self) -> dict[str, int]: ...


class InMemoryGraphRepository:
    """GraphDocument를 인메모리 인덱스로 올린 구현."""

    def __init__(self, doc: GraphDocument) -> None:
        self._by_id: dict[str, Entity] = {e.id: e for e in doc.entities}
        self._sources: dict[str, Source] = {s.id: s for s in doc.sources}
        self._out: dict[str, list[Statement]] = {}
        self._in: dict[str, list[Statement]] = {}
        for stmt in doc.statements:
            self._out.setdefault(stmt.subject, []).append(stmt)
            self._in.setdefault(stmt.object, []).append(stmt)
        # 이름·alias 소문자 → entity id (부분일치 검색용)
        self._name_index: list[tuple[str, str]] = []
        for entity in doc.entities:
            terms = [entity.name, *entity.aliases]
            for term in terms:
                self._name_index.append((term.lower(), entity.id))

    @classmethod
    def from_path(cls, path: str | Path) -> InMemoryGraphRepository:
        """시드 JSON을 검증 로드해 저장소를 만든다."""
        return cls(load_graph(path))

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._by_id.get(entity_id)

    def get_source(self, source_id: str) -> Source | None:
        return self._sources.get(source_id)

    def search_entities(self, query: str, limit: int = 20) -> list[Entity]:
        q = query.strip().lower()
        if not q:
            return []
        seen: dict[str, Entity] = {}
        for term, entity_id in self._name_index:
            if q in term and entity_id not in seen:
                entity = self._by_id[entity_id]
                seen[entity_id] = entity
                if len(seen) >= limit:
                    break
        return list(seen.values())

    def statements_of(self, entity_id: str) -> list[Statement]:
        """엔티티가 subject 또는 object인 모든 statement (중복 제거)."""
        out = self._out.get(entity_id, [])
        inc = self._in.get(entity_id, [])
        merged: dict[str, Statement] = {s.id: s for s in out}
        for s in inc:
            merged.setdefault(s.id, s)
        return list(merged.values())

    def outgoing(self, entity_id: str) -> list[Statement]:
        return list(self._out.get(entity_id, []))

    def incoming(self, entity_id: str) -> list[Statement]:
        return list(self._in.get(entity_id, []))

    def stats(self) -> dict[str, int]:
        return {
            "entities": len(self._by_id),
            "sources": len(self._sources),
            "statements": sum(len(v) for v in self._out.values()),
        }
