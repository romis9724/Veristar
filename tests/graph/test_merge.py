"""증분 병합 테스트 — upsert·중복제거·SUPERSEDED 조정·멱등성."""

from __future__ import annotations

from datetime import datetime

from veristar.graph import merge
from veristar.ontology.enums import Grade, Predicate, SourceType, Status
from veristar.ontology.graph import GraphDocument
from veristar.ontology.models import Person, Source, Statement


def _person(qid: str, name: str) -> Person:
    return Person(id=qid, name=name, created_at=datetime(2026, 1, 1))


def _src(qid: str) -> Source:
    return Source(
        id=f"src_wd_{qid}",
        source_type=SourceType.WIKIDATA_VERIFIED,
        publisher="Wikidata",
        url=f"https://www.wikidata.org/wiki/{qid}",
        title=qid,
        license="CC0",
    )


def _stmt(sid: str, subject: str, obj: str, src: str, status: Status = Status.ACTIVE) -> Statement:
    return Statement(
        id=sid,
        subject=subject,
        predicate=Predicate.MEMBER_OF,
        object=obj,
        grade=Grade.OFFICIAL,
        status=status,
        sources=[src],
    )


def _doc(entities=(), sources=(), statements=()) -> GraphDocument:
    return GraphDocument(
        entities=list(entities), sources=list(sources), statements=list(statements)
    )


def test_merge_into_empty_adds_all() -> None:
    incoming = _doc(
        [_person("wd:Q1", "A")], [_src("Q1")], [_stmt("s1", "wd:Q1", "wd:Q2", "src_wd_Q1")]
    )
    merged, report = merge(_doc(), incoming)
    assert len(merged.entities) == 1
    assert report.added_entities == 1
    assert report.added_statements == 1
    assert report.superseded_statements == 0


def test_merge_dedups_by_id() -> None:
    base = _doc([_person("wd:Q1", "A")], [_src("Q1")], [_stmt("s1", "wd:Q1", "wd:Q2", "src_wd_Q1")])
    incoming = _doc(
        [_person("wd:Q1", "A (updated)")],
        [_src("Q1")],
        [_stmt("s1", "wd:Q1", "wd:Q2", "src_wd_Q1")],
    )
    merged, report = merge(base, incoming)
    assert len(merged.entities) == 1  # 중복 없음
    assert len(merged.statements) == 1
    assert report.updated_entities == 1
    assert report.added_entities == 0
    # incoming이 우선 → 이름 갱신
    assert merged.entities[0].name == "A (updated)"


def test_merge_accumulates_different_roots() -> None:
    base = _doc([_person("wd:Q1", "A")], [_src("Q1")], [_stmt("s1", "wd:Q1", "wd:QG", "src_wd_Q1")])
    incoming = _doc(
        [_person("wd:Q2", "B")], [_src("Q2")], [_stmt("s2", "wd:Q2", "wd:QG", "src_wd_Q2")]
    )
    merged, _ = merge(base, incoming)
    assert {e.id for e in merged.entities} == {"wd:Q1", "wd:Q2"}
    assert {s.id for s in merged.statements} == {"s1", "s2"}


def test_vanished_fact_from_reingested_source_is_superseded() -> None:
    # base: Q1 출처의 s1, s2. incoming: Q1 재수집인데 s1만 나옴 → s2는 SUPERSEDED
    base = _doc(
        [_person("wd:Q1", "A")],
        [_src("Q1")],
        [_stmt("s1", "wd:Q1", "wd:QG", "src_wd_Q1"), _stmt("s2", "wd:Q1", "wd:QH", "src_wd_Q1")],
    )
    incoming = _doc(
        [_person("wd:Q1", "A")], [_src("Q1")], [_stmt("s1", "wd:Q1", "wd:QG", "src_wd_Q1")]
    )
    merged, report = merge(base, incoming)
    by_id = {s.id: s for s in merged.statements}
    assert by_id["s1"].status is Status.ACTIVE
    assert by_id["s2"].status is Status.SUPERSEDED  # 삭제 아님, 보존
    assert report.superseded_statements == 1


def test_untouched_source_preserved() -> None:
    # base: Q2 출처의 s2. incoming은 Q1만 재수집 → s2(다른 출처)는 건드리지 않음
    base = _doc([_person("wd:Q2", "B")], [_src("Q2")], [_stmt("s2", "wd:Q2", "wd:QG", "src_wd_Q2")])
    incoming = _doc(
        [_person("wd:Q1", "A")], [_src("Q1")], [_stmt("s1", "wd:Q1", "wd:QG", "src_wd_Q1")]
    )
    merged, report = merge(base, incoming)
    by_id = {s.id: s for s in merged.statements}
    assert by_id["s2"].status is Status.ACTIVE  # 보존
    assert report.superseded_statements == 0


def test_idempotent_remerge() -> None:
    doc = _doc([_person("wd:Q1", "A")], [_src("Q1")], [_stmt("s1", "wd:Q1", "wd:QG", "src_wd_Q1")])
    merged, report = merge(doc, doc)
    assert report.superseded_statements == 0
    assert report.added_statements == 0
    assert {s.status for s in merged.statements} == {Status.ACTIVE}


def test_merged_graph_validates() -> None:
    base = _doc([_person("wd:Q1", "A")], [_src("Q1")], [_stmt("s1", "wd:Q1", "wd:QG", "src_wd_Q1")])
    incoming = _doc(
        [_person("wd:Q2", "B")], [_src("Q2")], [_stmt("s2", "wd:Q2", "wd:QG", "src_wd_Q2")]
    )
    merged, _ = merge(base, incoming)
    assert merged.validate_cross_references() == []
