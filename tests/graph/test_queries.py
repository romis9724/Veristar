"""조회 연산 테스트 — 필터·연표·이웃·출처 부착."""

from __future__ import annotations

from datetime import date

from veristar.graph import (
    InMemoryGraphRepository,
    StatementFilter,
    entity_detail,
    neighbors,
    statements_for,
    timeline,
)
from veristar.ontology.enums import Grade, Predicate, Status


def test_entity_detail_counts(repo: InMemoryGraphRepository) -> None:
    detail = entity_detail(repo, "wd:Q1")
    assert detail is not None
    assert detail.outgoing_count == 2  # s_member(active) + s_old(superseded)
    assert detail.incoming_count == 0
    assert entity_detail(repo, "wd:Q404") is None


def test_statements_default_filter_active_only(repo: InMemoryGraphRepository) -> None:
    # 기본 필터는 ACTIVE만 → SUPERSEDED s_old 제외
    views = statements_for(repo, "wd:Q1")
    assert {v.statement.id for v in views} == {"s_member"}


def test_statements_include_superseded_when_requested(repo: InMemoryGraphRepository) -> None:
    filt = StatementFilter(statuses=frozenset({Status.ACTIVE, Status.SUPERSEDED}))
    views = statements_for(repo, "wd:Q1", filt)
    assert {v.statement.id for v in views} == {"s_member", "s_old"}


def test_direction_and_other_resolution(repo: InMemoryGraphRepository) -> None:
    [view] = statements_for(repo, "wd:Q1")
    assert view.direction == "out"
    assert view.other_id == "wd:Q2"
    assert view.other is not None and view.other.name == "그룹 G"


def test_other_is_none_when_not_in_graph(repo: InMemoryGraphRepository) -> None:
    filt = StatementFilter(statuses=frozenset({Status.SUPERSEDED}))
    [view] = statements_for(repo, "wd:Q1", filt)
    assert view.other_id == "wd:Q9"
    assert view.other is None  # 그래프에 없는 엔티티


def test_sources_attached_with_grade(repo: InMemoryGraphRepository) -> None:
    [view] = statements_for(repo, "wd:Q1")
    assert len(view.sources) == 1
    assert view.sources[0].license == "CC0"
    assert view.statement.grade is Grade.OFFICIAL


def test_grade_filter(repo: InMemoryGraphRepository) -> None:
    filt = StatementFilter(grades=frozenset({Grade.REPORTED}))
    views = statements_for(repo, "wd:Q2", filt)
    assert {v.statement.id for v in views} == {"s_affil"}  # OFFICIAL인 s_member 제외


def test_predicate_filter(repo: InMemoryGraphRepository) -> None:
    filt = StatementFilter(predicates=frozenset({Predicate.AFFILIATED_WITH}))
    assert {v.statement.id for v in statements_for(repo, "wd:Q2", filt)} == {"s_affil"}


def test_period_filter_overlap(repo: InMemoryGraphRepository) -> None:
    # 2011년에 유효했던 관계만 → s_old([2010,2015])만, ACTIVE 포함 필터로
    filt = StatementFilter(
        statuses=frozenset({Status.ACTIVE, Status.SUPERSEDED}),
        date_from=date(2011, 1, 1),
        date_to=date(2011, 12, 31),
    )
    assert {v.statement.id for v in statements_for(repo, "wd:Q1", filt)} == {"s_old"}


def test_timeline_sorted_by_valid_from(repo: InMemoryGraphRepository) -> None:
    filt = StatementFilter(statuses=frozenset({Status.ACTIVE, Status.SUPERSEDED}))
    views = timeline(repo, "wd:Q1", filt)
    assert [v.statement.id for v in views] == ["s_old", "s_member"]  # 2010 < 2016


def test_neighbors_dedup_and_resolved(repo: InMemoryGraphRepository) -> None:
    # Q2의 이웃: Q1(member, in) + Q3(affil, out). 전체 등급/상태로.
    filt = StatementFilter(grades=None)
    others = {v.other_id for v in neighbors(repo, "wd:Q2", filt)}
    assert others == {"wd:Q1", "wd:Q3"}
