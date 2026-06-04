"""그래프 증분 병합 — 여러 수집 실행을 영속 그래프에 누적·중복제거한다.

재수집된 출처에 한해, 이번에 사라진 statement는 삭제하지 않고 SUPERSEDED로
보존한다(스키마 §2.3 — 변화 이력 자체가 검증 자산). Karpathy `ingest`/`lint` 의미.
"""

from __future__ import annotations

from dataclasses import dataclass

from veristar.ontology.enums import Status
from veristar.ontology.graph import GraphDocument
from veristar.ontology.models import Statement


@dataclass(frozen=True)
class MergeReport:
    added_entities: int
    updated_entities: int
    added_statements: int
    updated_statements: int
    superseded_statements: int

    def summary(self) -> str:
        return (
            f"entities +{self.added_entities}/~{self.updated_entities}, "
            f"statements +{self.added_statements}/~{self.updated_statements}, "
            f"superseded {self.superseded_statements}"
        )


def merge(base: GraphDocument, incoming: GraphDocument) -> tuple[GraphDocument, MergeReport]:
    """base에 incoming을 병합. id 기준 upsert + 재수집 출처의 사라진 statement는 SUPERSEDED.

    reconcile 대상 출처 = incoming에 등장한 모든 source id(이번에 실제 재수집된 페이지).
    그 출처를 참조하던 base statement가 incoming에 없으면 SUPERSEDED로 보존한다.
    다른 출처(이번에 안 건드린 루트)의 데이터는 그대로 둔다.
    """
    # --- 엔티티 upsert ---
    entities = {e.id: e for e in base.entities}
    added_e = updated_e = 0
    for e in incoming.entities:
        if e.id in entities:
            updated_e += 1
        else:
            added_e += 1
        entities[e.id] = e

    # --- 출처 upsert ---
    sources = {s.id: s for s in base.sources}
    for src in incoming.sources:
        sources[src.id] = src

    # --- statement upsert ---
    statements = {s.id: s for s in base.statements}
    incoming_ids = {s.id for s in incoming.statements}
    added_s = updated_s = 0
    for stmt in incoming.statements:
        if stmt.id in statements:
            updated_s += 1
        else:
            added_s += 1
        statements[stmt.id] = stmt

    # --- SUPERSEDED 조정: 재수집 출처에서 사라진 statement ---
    reconciled_sources = {sid for s in incoming.statements for sid in s.sources}
    superseded = 0
    for sid, stmt in statements.items():
        if sid in incoming_ids:
            continue  # 이번에 갱신됨
        if stmt.status is not Status.ACTIVE:
            continue  # 이미 비활성
        # 이 statement가 재수집된 출처에만 근거하는데 이번에 안 나왔다 → 사라진 사실
        if stmt.sources and all(src in reconciled_sources for src in stmt.sources):
            statements[sid] = _supersede(stmt)
            superseded += 1

    merged = GraphDocument(
        entities=list(entities.values()),
        sources=list(sources.values()),
        statements=list(statements.values()),
    )
    report = MergeReport(
        added_entities=added_e,
        updated_entities=updated_e,
        added_statements=added_s,
        updated_statements=updated_s,
        superseded_statements=superseded,
    )
    return merged, report


def _supersede(stmt: Statement) -> Statement:
    return stmt.model_copy(update={"status": Status.SUPERSEDED})
