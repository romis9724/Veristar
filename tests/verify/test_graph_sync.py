"""그래프 승격(graph_sync) 단위 테스트."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from veristar.generate.llm import LLMResult
from veristar.graph import InMemoryGraphRepository
from veristar.ontology.enums import Grade, Predicate
from veristar.ontology.graph import GraphDocument
from veristar.ontology.models import Group, Organization, Person
from veristar.vault.store import ConfidenceLevel, VaultDoc, VaultStore
from veristar.verify.graph_sync import (
    SyncReport,
    _build_entity_list,
    _is_valid_direction,
    _source_id,
    sync_high_to_graph,
)


@pytest.fixture
def minimal_seed(tmp_path: Path) -> Path:
    """엔티티 3개짜리 최소 시드."""
    from veristar.ingest.wikidata.seed import write_seed

    # 이름이 충분히 길어야 벡터 검증 없이 substring 매칭으로 통과 (SHORT_NAME_LEN=3)
    person = Person(id="wd:Q1", name="모모 (TWICE)", created_at=datetime(2024, 1, 1))
    group = Group(id="wd:Q2", name="트와이스", created_at=datetime(2024, 1, 1))
    org = Organization(id="wd:Q3", name="JYP 엔터테인먼트", created_at=datetime(2024, 1, 1))
    doc = GraphDocument(entities=[person, group, org], sources=[], statements=[])
    seed = tmp_path / "seed.json"
    write_seed(doc, seed)
    return seed


@pytest.fixture
def vault_with_high(tmp_path: Path) -> VaultStore:
    store = VaultStore(tmp_path / "vault")
    doc = VaultDoc(
        id="wikipedia-ko-트와이스",
        title="트와이스 (Wikipedia KO)",
        content="트와이스는 JYP 엔터테인먼트 소속 걸그룹이다. 모모 (TWICE)는 트와이스 멤버이다.",
        source_type="wikipedia",
        source_url="https://ko.wikipedia.org/wiki/트와이스",
        confidence=ConfidenceLevel.HIGH,
        entity_refs=["트와이스"],
        retrieved=date(2024, 1, 1),
        license="CC BY-SA 4.0",
    )
    store.write(doc)
    return store


def test_source_id_deterministic() -> None:
    doc = VaultDoc(
        id="test",
        title="t",
        content="c",
        source_type="wikipedia",
        source_url="https://example.com",
    )
    assert _source_id(doc) == _source_id(doc)
    assert _source_id(doc).startswith("src_vault_")


def test_build_entity_list_includes_type() -> None:
    person = Person(id="wd:Q1", name="다현", created_at=datetime(2024, 1, 1))
    group = Group(id="wd:Q2", name="트와이스", created_at=datetime(2024, 1, 1))
    result = _build_entity_list([person, group])
    assert "Person" in result
    assert "Group" in result
    assert "다현" in result


def test_is_valid_direction_group_member_of_person(repo: InMemoryGraphRepository) -> None:
    """그룹이 person을 memberOf로 가리키면 방향 오류 → False."""
    assert _is_valid_direction("wd:Q2", "memberOf", "wd:Q1", repo) is False


def test_is_valid_direction_person_member_of_group(repo: InMemoryGraphRepository) -> None:
    """개인이 그룹을 memberOf로 가리키면 유효 → True."""
    assert _is_valid_direction("wd:Q1", "memberOf", "wd:Q2", repo) is True


def test_is_valid_direction_unknown_entity(repo: InMemoryGraphRepository) -> None:
    assert _is_valid_direction("wd:Q999", "memberOf", "wd:Q1", repo) is False


def test_sync_high_extracts_fact(vault_with_high: VaultStore, minimal_seed: Path) -> None:
    """유효한 사실이 추출되면 그래프에 statement가 추가된다."""
    llm_response = json.dumps(
        {"facts": [{"subject_id": "wd:Q1", "predicate": "memberOf", "object_id": "wd:Q2"}]}
    )
    mock_result = LLMResult(ok=True, text=llm_response, model="test", error=None)

    with patch("veristar.verify.graph_sync.chat", return_value=mock_result):
        report = sync_high_to_graph(vault_with_high, minimal_seed, dry_run=True)

    assert report.total_docs == 1
    assert report.new_statements == 1
    assert report.extracted == 1


def test_sync_high_invalid_direction_rejected(
    vault_with_high: VaultStore, minimal_seed: Path
) -> None:
    """그룹→개인 방향의 memberOf는 거부된다."""
    llm_response = json.dumps(
        {"facts": [{"subject_id": "wd:Q2", "predicate": "memberOf", "object_id": "wd:Q1"}]}
    )
    mock_result = LLMResult(ok=True, text=llm_response, model="test", error=None)

    with patch("veristar.verify.graph_sync.chat", return_value=mock_result):
        report = sync_high_to_graph(vault_with_high, minimal_seed, dry_run=True)

    assert report.new_statements == 0


def test_sync_high_llm_failure_skipped(vault_with_high: VaultStore, minimal_seed: Path) -> None:
    mock_result = LLMResult(ok=False, text="", model="test", error="timeout")

    with patch("veristar.verify.graph_sync.chat", return_value=mock_result):
        report = sync_high_to_graph(vault_with_high, minimal_seed, dry_run=True)

    assert report.new_statements == 0
    assert report.skipped == 1


def test_sync_high_writes_to_seed(vault_with_high: VaultStore, minimal_seed: Path) -> None:
    """dry_run=False이면 실제로 시드 파일이 갱신된다."""
    from veristar.ontology.graph import load_graph

    llm_response = json.dumps(
        {"facts": [{"subject_id": "wd:Q1", "predicate": "memberOf", "object_id": "wd:Q2"}]}
    )
    mock_result = LLMResult(ok=True, text=llm_response, model="test", error=None)

    with patch("veristar.verify.graph_sync.chat", return_value=mock_result):
        sync_high_to_graph(vault_with_high, minimal_seed, dry_run=False)

    updated = load_graph(minimal_seed)
    new_stmts = [s for s in updated.statements if s.predicate == Predicate.MEMBER_OF]
    assert len(new_stmts) == 1
    assert new_stmts[0].grade == Grade.REPORTED  # vault 추출은 항상 REPORTED (검토 후 승격)


def test_sync_missing_seed(vault_with_high: VaultStore, tmp_path: Path) -> None:
    report = sync_high_to_graph(vault_with_high, tmp_path / "nonexistent.json")
    assert report.total_docs == 0


def test_sync_report_summary() -> None:
    r = SyncReport(total_docs=10, extracted=5, new_sources=10, new_statements=5)
    s = r.summary()
    assert "stmt+5" in s
    assert "extracted=5" in s
