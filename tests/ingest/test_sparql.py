"""SPARQL 발견 클라이언트 테스트 (실제 WDQS 호출 없음, Fake runner)."""

from __future__ import annotations

from veristar.ingest.wikidata.sparql import (
    OCCUPATION_GROUPS,
    DiscoveredEntity,
    _kowiki_title,
    _qid_from_uri,
    discover_korean_celebrities,
)


class FakeRunner:
    """직업별 쿼리에 미리 정한 결과를 돌려주는 Fake SPARQL 실행기."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = responses
        self._i = 0

    def run(self, query: str) -> dict:
        empty: dict = {"results": {"bindings": []}}
        r = self._responses[self._i] if self._i < len(self._responses) else empty
        self._i += 1
        return r


def _binding(qid: str, label: str, article: str | None = None, key: str = "p") -> dict:
    b = {
        key: {"value": f"http://www.wikidata.org/entity/{qid}"},
        f"{key}Label": {"value": label},
    }
    if article:
        b["article"] = {"value": article}
    return b


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────


def test_qid_from_uri() -> None:
    assert _qid_from_uri("http://www.wikidata.org/entity/Q12345") == "Q12345"


def test_kowiki_title_decodes() -> None:
    b = {"article": {"value": "https://ko.wikipedia.org/wiki/%EC%95%84%EC%9D%B4%EC%9C%A0"}}
    assert _kowiki_title(b) == "아이유"


def test_kowiki_title_underscore_to_space() -> None:
    b = {"article": {"value": "https://ko.wikipedia.org/wiki/Stray_Kids"}}
    assert _kowiki_title(b) == "Stray Kids"


def test_kowiki_title_empty() -> None:
    assert _kowiki_title({}) == ""


# ─── discover ────────────────────────────────────────────────────────────────


def test_discover_single_occupation() -> None:
    resp = {
        "results": {
            "bindings": [
                _binding("Q12345", "아이유", "https://ko.wikipedia.org/wiki/아이유"),
                _binding("Q67890", "태양", "https://ko.wikipedia.org/wiki/태양"),
            ]
        }
    }
    runner = FakeRunner([resp])
    results = discover_korean_celebrities(runner, ["singer"], sleep_sec=0)

    assert len(results) == 2
    assert results[0].qid == "Q12345"
    assert results[0].name == "아이유"
    assert results[0].category == "singer"
    assert results[0].occupation_qids == OCCUPATION_GROUPS["singer"]


def test_discover_dedupes_across_occupations() -> None:
    """같은 QID가 여러 직업에서 나와도 한 번만."""
    singer_resp = {
        "results": {"bindings": [_binding("Q1", "다재능", "https://ko.wikipedia.org/wiki/A")]}
    }
    actor_resp = {
        "results": {"bindings": [_binding("Q1", "다재능", "https://ko.wikipedia.org/wiki/A")]}
    }
    runner = FakeRunner([singer_resp, actor_resp])
    results = discover_korean_celebrities(runner, ["singer", "actor"], sleep_sec=0)
    assert len(results) == 1
    assert results[0].category == "singer"  # 첫 매칭 유지


def test_discover_group_query() -> None:
    resp = {
        "results": {
            "bindings": [
                {
                    "g": {"value": "http://www.wikidata.org/entity/Q46134670"},
                    "gLabel": {"value": "스트레이 키즈"},
                    "article": {"value": "https://ko.wikipedia.org/wiki/스트레이_키즈"},
                }
            ]
        }
    }
    runner = FakeRunner([resp])
    results = discover_korean_celebrities(runner, ["group"], sleep_sec=0)
    assert len(results) == 1
    assert results[0].qid == "Q46134670"
    assert results[0].category == "group"
    assert results[0].occupation_qids == []


def test_discover_unknown_category_skipped() -> None:
    runner = FakeRunner([])
    results = discover_korean_celebrities(runner, ["unknown_cat"], sleep_sec=0)
    assert results == []


def test_discover_query_failure_continues() -> None:
    """한 직업 쿼리가 실패해도 나머지는 계속."""

    class FailingThenOk:
        def __init__(self) -> None:
            self._calls = 0

        def run(self, query: str) -> dict:
            self._calls += 1
            if self._calls == 1:
                raise RuntimeError("WDQS timeout")
            return {
                "results": {
                    "bindings": [_binding("Q9", "배우B", "https://ko.wikipedia.org/wiki/B")]
                }
            }

    results = discover_korean_celebrities(FailingThenOk(), ["singer", "actor"], sleep_sec=0)
    assert len(results) == 1
    assert results[0].qid == "Q9"


def test_discover_no_kowiki_uses_label_as_title() -> None:
    resp = {"results": {"bindings": [_binding("Q5", "무명가수")]}}  # article 없음
    runner = FakeRunner([resp])
    results = discover_korean_celebrities(runner, ["singer"], require_kowiki=False, sleep_sec=0)
    assert len(results) == 1
    assert results[0].kowiki_title == "무명가수"


def test_discovered_entity_frozen() -> None:
    d = DiscoveredEntity(qid="Q1", name="n", kowiki_title="t", category="singer")
    import pytest

    with pytest.raises(AttributeError):
        d.name = "x"  # type: ignore[misc]
