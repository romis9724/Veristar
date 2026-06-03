"""골든 픽스처 테스트 — data/examples/sample.json이 전체 validation을 통과한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from veristar.ontology import GraphValidationError, load_graph
from veristar.ontology.enums import EntityType

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "examples" / "sample.json"


def test_sample_loads_and_validates() -> None:
    doc = load_graph(SAMPLE)
    assert len(doc.entities) == 6
    assert len(doc.sources) == 3
    assert len(doc.statements) == 5
    # 교차참조 위반 0건
    assert doc.validate_cross_references() == []


def test_sample_entity_types_parsed_into_union() -> None:
    doc = load_graph(SAMPLE)
    types = {e.type for e in doc.entities}
    assert types == set(EntityType)


def test_sample_all_statements_official_and_nonsensitive() -> None:
    # sample은 OFFICIAL·비민감만 모델링한다는 주석을 코드로 확인
    from veristar.ontology import official_nonsensitive

    doc = load_graph(SAMPLE)
    assert len(official_nonsensitive(doc)) == len(doc.statements)


def test_load_graph_raises_on_cross_reference_violation(tmp_path: Path) -> None:
    # source를 비운 그래프 → 규칙 2 위반으로 GraphValidationError
    bad = tmp_path / "bad.json"
    bad.write_text(
        """
        {
          "entities": [],
          "sources": [],
          "statements": [
            {"id": "s1", "subject": "a", "predicate": "memberOf",
             "object": "b", "grade": "OFFICIAL", "status": "ACTIVE",
             "sources": ["ghost"]}
          ]
        }
        """,
        encoding="utf-8",
    )
    with pytest.raises(GraphValidationError) as exc:
        load_graph(bad)
    assert any(v.rule == 2 for v in exc.value.violations)
