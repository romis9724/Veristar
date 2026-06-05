"""GraphDocument 컨테이너 + 교차참조 validation (스키마 §5 규칙 2·3).

모델 레벨에서 잡히는 규칙 1·4·6과 달리, 규칙 2·3은 전체 그래프(특히 sources)를
함께 봐야 하므로 여기서 검사한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from .grading_map import is_grade_supported, max_grade_for_source_types
from .models import Entity, Source, Statement


@dataclass(frozen=True)
class Violation:
    """validation 위반 1건. rule은 스키마 §5의 규칙 번호."""

    statement_id: str
    rule: int
    message: str


class GraphValidationError(ValueError):
    """교차참조 validation 위반이 1건 이상 있을 때 발생."""

    def __init__(self, violations: list[Violation]) -> None:
        self.violations = violations
        lines = "\n".join(f"  - [{v.statement_id}] rule {v.rule}: {v.message}" for v in violations)
        super().__init__(f"{len(violations)} validation violation(s):\n{lines}")


class GraphDocument(BaseModel):
    """엔티티·출처·Statement 묶음 (data/examples/sample.json 구조와 1:1).

    파싱 시점에 규칙 1·4·6이 Pydantic으로 강제된다.
    규칙 2·3은 validate_cross_references()로 별도 검사.
    """

    entities: list[Entity]
    sources: list[Source]
    statements: list[Statement]

    def validate_cross_references(self) -> list[Violation]:
        """규칙 2·3 위반 목록을 모아 반환 (없으면 빈 목록)."""
        violations: list[Violation] = []
        sources_by_id: dict[str, Source] = {s.id: s for s in self.sources}

        from .enums import Status

        for stmt in self.statements:
            # RETRACTED / SUPERSEDED 는 이미 무효화된 사실 — 검증 제외
            if stmt.status in (Status.RETRACTED, Status.SUPERSEDED):
                continue

            # 규칙 2: 참조된 source id가 실제로 존재
            missing = [sid for sid in stmt.sources if sid not in sources_by_id]
            for sid in missing:
                violations.append(Violation(stmt.id, 2, f"unknown source id: {sid!r}"))

            # 규칙 3: grade가 출처 유형이 받쳐주는 등급과 모순되지 않음
            present_types = [
                sources_by_id[sid].source_type for sid in stmt.sources if sid in sources_by_id
            ]
            if present_types and not is_grade_supported(stmt.grade, present_types):
                ceiling = max_grade_for_source_types(present_types)
                violations.append(
                    Violation(
                        stmt.id,
                        3,
                        f"grade {stmt.grade.value} exceeds what sources support "
                        f"(max {ceiling.value if ceiling else 'n/a'})",
                    )
                )

        return violations


def load_graph(path: str | Path) -> GraphDocument:
    """JSON 파일에서 그래프를 읽고 전체 validation(규칙 1~4,6)을 강제한다.

    규칙 1·4·6 위반 → pydantic ValidationError.
    규칙 2·3 위반 → GraphValidationError.
    """
    raw = Path(path).read_text(encoding="utf-8")
    doc = GraphDocument.model_validate_json(raw)
    violations = doc.validate_cross_references()
    if violations:
        raise GraphValidationError(violations)
    return doc
