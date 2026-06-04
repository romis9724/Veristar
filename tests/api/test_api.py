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


def test_htmx_self_hosted(client: TestClient) -> None:
    # htmx는 CDN이 아니라 self-host 정적 파일로 서빙된다
    assert "/static/htmx.min.js" in client.get("/").text
    r = client.get("/static/htmx.min.js")
    assert r.status_code == 200
    assert "htmx" in r.text


def test_ui_index_renders(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    # index.html은 RAG 검색 UI로 업데이트됨 ("지식 검색" 텍스트 포함)
    assert r.status_code == 200
    assert "검색" in r.text


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


# ─── 새 UI 엔드포인트 ─────────────────────────────────────────────────────────


def test_graph_data_returns_nodes(client: TestClient) -> None:
    r = client.get("/api/graph/data")
    assert r.status_code == 200
    d = r.json()["data"]
    assert "nodes" in d
    assert "links" in d
    assert len(d["nodes"]) >= 2  # repo에 엔티티 있음


def test_graph_data_grade_filter(client: TestClient) -> None:
    r = client.get("/api/graph/data", params={"grade": "OFFICIAL"})
    assert r.status_code == 200
    d = r.json()["data"]
    for lnk in d["links"]:
        assert lnk["grade"] == "OFFICIAL"


def test_entity_tree_returns_types(client: TestClient) -> None:
    r = client.get("/api/tree")
    assert r.status_code == 200
    d = r.json()["data"]
    # 최소 1개 이상 타입이 있어야 함
    assert len(d) >= 1
    for items in d.values():
        assert isinstance(items, list)
        assert all("id" in i and "name" in i for i in items)


def test_vault_docs_endpoint(client: TestClient) -> None:
    r = client.get("/api/vault/docs", params={"limit": 5})
    assert r.status_code == 200
    docs = r.json()["data"]
    assert isinstance(docs, list)


def test_vault_doc_detail_not_found(client: TestClient) -> None:
    r = client.get("/api/vault/doc/nonexistent-id-xyz")
    assert r.status_code == 404


def test_ui_graph_page_renders(client: TestClient) -> None:
    r = client.get("/ui/graph")
    assert r.status_code == 200
    assert "d3.min.js" in r.text
    assert "graph-canvas" in r.text


def test_ui_vault_page_renders(client: TestClient) -> None:
    r = client.get("/ui/vault")
    assert r.status_code == 200
    assert "vault" in r.text.lower()
    assert "file-tree" in r.text


def test_ui_qa_page_renders_multiturn(client: TestClient) -> None:
    r = client.get("/ui/qa")
    assert r.status_code == 200
    assert "chat-box" in r.text
    assert "send-btn" in r.text


def test_ui_vault_doc_partial_missing(client: TestClient) -> None:
    r = client.get("/ui/vault/doc", params={"id": "does-not-exist"})
    assert r.status_code == 404


def test_ui_graph_has_nav_link(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "/ui/graph" in r.text
    assert "/ui/vault" in r.text


# ─── 새 기능 추가 테스트 ──────────────────────────────────────────────────────

def test_pipeline_status_idle(client: TestClient) -> None:
    r = client.get("/api/pipeline/status")
    assert r.status_code == 200
    d = r.json()["data"]
    assert "status" in d
    assert "log_count" in d


def test_pipeline_logs_empty(client: TestClient) -> None:
    r = client.get("/api/pipeline/logs")
    assert r.status_code == 200
    d = r.json()["data"]
    assert "logs" in d
    assert isinstance(d["logs"], list)


def test_rag_search_basic(client: TestClient) -> None:
    r = client.get("/api/search/rag", params={"q": "아티스트"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert "results" in d
    assert "query" in d
    assert d["query"] == "아티스트"


def test_rag_search_sensitive_filtered(client: TestClient) -> None:
    # include_sensitive=false 기본값 — 민감 문서 제외
    r = client.get("/api/search/rag", params={"q": "아티스트", "include_sensitive": "false"})
    assert r.status_code == 200
    # 민감 문서가 결과에 없어야 함
    for item in r.json()["data"]["results"]:
        assert item.get("sensitive", False) is False


def test_collect_ui_page(client: TestClient) -> None:
    r = client.get("/ui/collect")
    assert r.status_code == 200
    assert "agent-panel" in r.text
    assert "파이프라인" in r.text


def test_rag_search_with_source_type(client: TestClient) -> None:
    r = client.get("/api/search/rag", params={"q": "아티스트", "source_type": "wikipedia"})
    assert r.status_code == 200
    d = r.json()["data"]
    # InMemory 모드: vault 없이도 entity 검색 결과 반환
    assert "results" in d
    assert "filters" in d


def test_rag_search_include_unverified(client: TestClient) -> None:
    r = client.get("/api/search/rag", params={"q": "그룹", "include_unverified": "true"})
    assert r.status_code == 200
    assert r.json()["data"]["query"] == "그룹"


def test_vault_doc_partial_no_id(client: TestClient) -> None:
    r = client.get("/ui/vault/doc")
    assert r.status_code == 200
    assert "선택" in r.text  # 빈 메시지
