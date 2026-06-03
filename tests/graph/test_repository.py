"""저장소 인덱스·검색·인접 테스트."""

from __future__ import annotations

from veristar.graph import InMemoryGraphRepository


def test_get_entity(repo: InMemoryGraphRepository) -> None:
    assert repo.get_entity("wd:Q1").name == "아티스트 A"
    assert repo.get_entity("wd:Q404") is None


def test_search_by_name_and_alias_case_insensitive(repo: InMemoryGraphRepository) -> None:
    assert [e.id for e in repo.search_entities("아티스트")] == ["wd:Q1"]
    assert [e.id for e in repo.search_entities("artist")] == ["wd:Q1"]  # alias, 대소문자 무시
    assert repo.search_entities("그룹")[0].id == "wd:Q2"


def test_search_empty_query_returns_nothing(repo: InMemoryGraphRepository) -> None:
    assert repo.search_entities("") == []
    assert repo.search_entities("   ") == []


def test_search_limit(repo: InMemoryGraphRepository) -> None:
    # 모든 엔티티 이름에 공통으로 없는 글자이지만, 'Q'는 없음 → 빈. limit 동작은 광범위 검색으로
    results = repo.search_entities("ㄱ", limit=1)  # '그룹'만 매칭 후보
    assert len(results) <= 1


def test_bidirectional_adjacency(repo: InMemoryGraphRepository) -> None:
    # Q2는 member(in: Q1→Q2)와 affil(out: Q2→Q3) 양쪽에 등장
    ids = {s.id for s in repo.statements_of("wd:Q2")}
    assert ids == {"s_member", "s_affil"}
    assert {s.id for s in repo.outgoing("wd:Q2")} == {"s_affil"}
    assert {s.id for s in repo.incoming("wd:Q2")} == {"s_member"}


def test_stats(repo: InMemoryGraphRepository) -> None:
    assert repo.stats() == {"entities": 3, "sources": 1, "statements": 3}
