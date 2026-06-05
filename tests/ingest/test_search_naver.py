"""NaverSearchProvider 단위 테스트 — httpx mock으로 네트워크 차단."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from veristar.ingest.search.naver import NaverSearchProvider, _strip_html


def test_strip_html_removes_tags_and_entities() -> None:
    raw = "<b>스트레이</b> 키즈 &amp; 친구들"
    assert _strip_html(raw) == "스트레이 키즈 & 친구들"


def test_unconfigured_returns_empty() -> None:
    """자격증명 없으면 호출하지 않고 빈 결과."""
    p = NaverSearchProvider(client_id="", client_secret="")
    assert p.is_configured() is False
    assert p.search("아무 쿼리") == []


def test_empty_query_returns_empty() -> None:
    p = NaverSearchProvider(client_id="cid", client_secret="sec")
    assert p.search("   ") == []


def _mock_response(items: list[dict[str, Any]]) -> httpx.Response:
    # raise_for_status를 호출 가능하게 하려면 request 객체가 필요
    resp = httpx.Response(200, json={"items": items})
    resp.request = httpx.Request("GET", "https://openapi.naver.com/v1/search/x.json")
    return resp


def test_search_parses_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """API 응답을 SearchResult로 변환."""
    item = {
        "title": "<b>스트레이</b> 키즈 신곡 발표",
        "link": "https://news.naver.com/article/001",
        "description": "<b>스트레이</b> 키즈가 신곡을 &quot;공개&quot;했다.",
        "pubDate": "Wed, 04 Jun 2026 10:23:00 +0900",
    }
    call_log: list[str] = []

    def fake_get(url: str, **kw: Any) -> httpx.Response:
        call_log.append(url)
        return _mock_response([item])

    monkeypatch.setattr(httpx, "get", fake_get)

    p = NaverSearchProvider(client_id="cid", client_secret="sec", kinds=("news",))
    results = p.search("스트레이 키즈", limit=5)

    assert len(results) == 1
    r = results[0]
    assert r.url == "https://news.naver.com/article/001"
    assert "<b>" not in r.title and "스트레이 키즈" in r.title
    assert '"공개"' in r.snippet
    assert r.source == "naver_news"
    assert r.published is not None and r.published.year == 2026
    assert len(call_log) == 1 and "news.json" in call_log[0]


def test_multiple_kinds_combined(monkeypatch: pytest.MonkeyPatch) -> None:
    """news + blog + webkr를 모두 호출해 결과를 합친다."""

    def fake_get(url: str, **kw: Any) -> httpx.Response:
        return _mock_response([{"title": "t", "link": f"{url}#x", "description": "d"}])

    monkeypatch.setattr(httpx, "get", fake_get)
    p = NaverSearchProvider(client_id="cid", client_secret="sec", kinds=("news", "blog", "webkr"))
    results = p.search("쿼리", limit=1)
    assert len(results) == 3
    sources = {r.source for r in results}
    assert sources == {"naver_news", "naver_blog", "naver_webkr"}


def test_api_error_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """네트워크 오류 시 예외 대신 빈 결과."""

    def fake_get(*a: Any, **kw: Any) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", fake_get)
    p = NaverSearchProvider(client_id="cid", client_secret="sec", kinds=("news",))
    assert p.search("쿼리") == []


def test_missing_link_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """link/originallink가 모두 없으면 결과에서 제외."""
    items = [
        {"title": "t1", "description": "d", "link": "https://ok/1"},
        {"title": "t2", "description": "d"},  # 링크 없음
    ]
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _mock_response(items))
    p = NaverSearchProvider(client_id="cid", client_secret="sec", kinds=("news",))
    results = p.search("쿼리")
    assert len(results) == 1
    assert results[0].url == "https://ok/1"
