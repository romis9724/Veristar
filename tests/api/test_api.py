"""JSON API + HTMX UI 엔드포인트 테스트 (FastAPI TestClient)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is None
    assert body["data"]["stats"]["entities"] == 2


def test_search_envelope(client: TestClient) -> None:
    r = client.get("/api/entities", params={"q": "아티스트"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert [e["id"] for e in data] == ["wd:Q1"]
    assert data[0]["type"] == "Person"


def test_search_by_alias(client: TestClient) -> None:
    r = client.get("/api/entities", params={"q": "artist"})
    assert [e["id"] for e in r.json()["data"]] == ["wd:Q1"]


def test_search_requires_query(client: TestClient) -> None:
    assert client.get("/api/entities").status_code == 422  # q 필수


def test_entity_detail(client: TestClient) -> None:
    r = client.get("/api/entities/wd:Q1")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["entity"]["name"] == "아티스트 A"
    assert data["outgoing_count"] == 1


def test_entity_detail_404(client: TestClient) -> None:
    assert client.get("/api/entities/wd:Q404").status_code == 404


def test_statements_include_sources_and_grade(client: TestClient) -> None:
    r = client.get("/api/entities/wd:Q1/statements")
    data = r.json()["data"]
    assert len(data) == 1
    stmt = data[0]
    assert stmt["predicate"] == "memberOf"
    assert stmt["grade"] == "OFFICIAL"
    assert stmt["other_name"] == "그룹 G"
    assert stmt["sources"][0]["license"] == "CC0"


def test_statements_grade_filter_excludes(client: TestClient) -> None:
    # REPORTED만 요청 → OFFICIAL뿐인 statement 없음
    r = client.get("/api/entities/wd:Q1/statements", params={"grade": "REPORTED"})
    assert r.json()["data"] == []


def test_timeline_and_neighbors(client: TestClient) -> None:
    assert client.get("/api/entities/wd:Q1/timeline").status_code == 200
    nb = client.get("/api/entities/wd:Q1/neighbors").json()["data"]
    assert {v["other_id"] for v in nb} == {"wd:Q2"}


def test_ui_index_renders(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "지식그래프" in r.text


def test_ui_search_fragment(client: TestClient) -> None:
    r = client.get("/ui/search", params={"q": "그룹"})
    assert r.status_code == 200
    assert "그룹 G" in r.text


def test_ui_entity_page_shows_grade_badge(client: TestClient) -> None:
    r = client.get("/ui/entities/wd:Q1")
    assert r.status_code == 200
    assert "OFFICIAL" in r.text
    assert "memberOf" in r.text


def test_ui_entity_404(client: TestClient) -> None:
    assert client.get("/ui/entities/wd:Q404").status_code == 404
