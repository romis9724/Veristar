"""엔드포인트 — JSON API(/api) + HTMX UI(/, /ui).

읽기 전용. 모든 statement 응답에 출처(등급)를 함께 싣는다.

저장소 선택:
  - app.state.use_postgres=True  → 요청마다 PostgreSQLGraphRepository (psycopg 커넥션)
  - app.state.use_postgres=False → app.state.repo (InMemoryGraphRepository)
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from veristar.generate import answer_question, generate_summary
from veristar.graph import (
    GraphRepository,
    StatementFilter,
    entity_detail,
    neighbors,
    statements_for,
    timeline,
)
from veristar.ontology.enums import Grade, Predicate, Status

from .schemas import detail_to_out, entity_to_out, ok, view_to_out

router = APIRouter()


def get_repo(request: Request) -> Iterator[GraphRepository]:
    """저장소 Depends — PostgreSQL 또는 InMemory를 투명하게 반환한다."""
    if getattr(request.app.state, "use_postgres", False):
        from pgvector.psycopg import register_vector  # type: ignore[import-untyped]

        from veristar.db.connection import get_conn
        from veristar.db.pg_repository import PostgreSQLGraphRepository

        conn = get_conn()
        register_vector(conn)
        try:
            yield PostgreSQLGraphRepository(conn)  # type: ignore[arg-type]
        finally:
            conn.close()
    else:
        yield request.app.state.repo


def statement_filter(
    grade: list[Grade] | None = Query(default=None),
    predicate: list[Predicate] | None = Query(default=None),
    status: list[Status] | None = Query(default=None),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> StatementFilter:
    return StatementFilter(
        grades=frozenset(grade) if grade else None,
        statuses=frozenset(status) if status else frozenset({Status.ACTIVE}),
        predicates=frozenset(predicate) if predicate else None,
        date_from=date_from,
        date_to=date_to,
    )


def _require_entity(repo: GraphRepository, entity_id: str) -> None:
    if repo.get_entity(entity_id) is None:
        raise HTTPException(status_code=404, detail=f"entity not found: {entity_id}")


# --- JSON API ---


@router.get("/api/health")
def health(request: Request, repo: GraphRepository = Depends(get_repo)) -> dict[str, object]:
    interval = float(os.environ.get("VERISTAR_REFRESH_INTERVAL_HOURS", "24"))
    use_pg = getattr(request.app.state, "use_postgres", False)
    return ok(
        {
            "status": "ok",
            "storage": "postgresql" if use_pg else "jsonl",
            "stats": repo.stats(),
            "auto_refresh": {
                "enabled": interval > 0,
                "interval_hours": interval if interval > 0 else None,
            },
        }
    )


@router.get("/api/entities")
def search_entities(
    q: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    repo: GraphRepository = Depends(get_repo),
) -> dict[str, object]:
    results = repo.search_entities(q, limit)
    return ok([entity_to_out(e) for e in results])


@router.get("/api/entities/{entity_id:path}/statements")
def entity_statements(
    entity_id: str,
    repo: GraphRepository = Depends(get_repo),
    filt: StatementFilter = Depends(statement_filter),
) -> dict[str, object]:
    _require_entity(repo, entity_id)
    return ok([view_to_out(v) for v in statements_for(repo, entity_id, filt)])


@router.get("/api/entities/{entity_id:path}/timeline")
def entity_timeline(
    entity_id: str,
    repo: GraphRepository = Depends(get_repo),
    filt: StatementFilter = Depends(statement_filter),
) -> dict[str, object]:
    _require_entity(repo, entity_id)
    return ok([view_to_out(v) for v in timeline(repo, entity_id, filt)])


@router.get("/api/entities/{entity_id:path}/neighbors")
def entity_neighbors(
    entity_id: str,
    repo: GraphRepository = Depends(get_repo),
    filt: StatementFilter = Depends(statement_filter),
) -> dict[str, object]:
    _require_entity(repo, entity_id)
    return ok([view_to_out(v) for v in neighbors(repo, entity_id, filt)])


@router.get("/api/entities/{entity_id:path}/summary")
def entity_summary(
    entity_id: str,
    repo: GraphRepository = Depends(get_repo),
) -> dict[str, object]:
    """재구성형 요약·연표 텍스트 (OFFICIAL·비민감 statement만, 추론 없음)."""
    result = generate_summary(repo, entity_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"entity not found: {entity_id}")
    return ok(
        {
            "entity_id": result.entity_id,
            "entity_name": result.entity_name,
            "summary": result.summary_text,
            "timeline": result.timeline_text,
            "statement_count": result.statement_count,
            "source_ids": result.source_ids,
        }
    )


@router.get("/api/entities/{entity_id:path}")
def entity_detail_endpoint(
    entity_id: str,
    repo: GraphRepository = Depends(get_repo),
) -> dict[str, object]:
    detail = entity_detail(repo, entity_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"entity not found: {entity_id}")
    return ok(detail_to_out(detail))


# --- Graph / Tree / Vault API ---


@router.get("/api/graph/data")
def graph_data(
    grade: list[Grade] | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    repo: GraphRepository = Depends(get_repo),
) -> dict[str, object]:
    """D3.js 그래프용 nodes + links JSON."""
    from veristar.ontology.enums import Status

    all_entities = repo.search_entities("", limit=500)
    if entity_type:
        all_entities = [e for e in all_entities if getattr(e, "type", "") == entity_type]

    entity_ids = {e.id for e in all_entities}
    grade_filter = frozenset(grade) if grade else None

    nodes = [
        {
            "id": e.id,
            "name": e.name,
            "type": str(getattr(e, "type", "Unknown")),
        }
        for e in all_entities
    ]

    links: list[dict[str, str]] = []
    seen_links: set[str] = set()
    for e in all_entities:
        for stmt in repo.outgoing(e.id):
            if stmt.status != Status.ACTIVE:
                continue
            if stmt.object not in entity_ids:
                continue
            if grade_filter and stmt.grade not in grade_filter:
                continue
            key = f"{stmt.subject}|{stmt.predicate}|{stmt.object}"
            if key not in seen_links:
                seen_links.add(key)
                links.append(
                    {
                        "source": stmt.subject,
                        "target": stmt.object,
                        "predicate": str(stmt.predicate),
                        "grade": str(stmt.grade),
                    }
                )

    return ok({"nodes": nodes, "links": links})


@router.get("/api/tree")
def entity_tree(
    repo: GraphRepository = Depends(get_repo),
) -> dict[str, object]:
    """엔티티 타입별 트리 구조."""
    from collections import defaultdict

    all_entities = repo.search_entities("", limit=500)
    tree: dict[str, list[dict[str, str]]] = defaultdict(list)
    for e in all_entities:
        etype = str(getattr(e, "type", "Unknown"))
        tree[etype].append({"id": e.id, "name": e.name})

    return ok({t: sorted(items, key=lambda x: x["name"]) for t, items in sorted(tree.items())})


@router.get("/api/vault/docs")
def vault_docs(
    source_type: str | None = Query(default=None),
    confidence: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, object]:
    """vault 문서 목록 (파일 탐색기용)."""
    from veristar.db.connection import is_available

    if is_available() and getattr(request.app.state, "use_postgres", False):
        from pgvector.psycopg import register_vector

        from veristar.db.connection import get_conn

        conn = get_conn()
        register_vector(conn)
        filters = []
        params: list[object] = []
        if source_type:
            filters.append("source_type = %s")
            params.append(source_type)
        if confidence:
            filters.append("confidence = %s")
            params.append(confidence)
        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        rows = conn.execute(
            f"SELECT id, title, source_type, confidence, sensitive, published "  # noqa: S608
            f"FROM vault_docs {where} ORDER BY source_type, title LIMIT %s",
            [*params, limit],
        ).fetchall()
        conn.close()
        docs = [
            {
                "id": r["id"],
                "title": r["title"],
                "source_type": r["source_type"],
                "confidence": r["confidence"],
                "sensitive": r["sensitive"],
                "published": str(r["published"]) if r["published"] else None,
            }
            for r in rows
        ]
    else:
        from veristar.vault.store import VaultStore

        store = VaultStore("vault")
        all_docs = store.list_docs(source_type=source_type)
        docs = [
            {
                "id": d.id,
                "title": d.title,
                "source_type": d.source_type,
                "confidence": d.confidence,
                "sensitive": d.sensitive,
                "published": str(d.published) if d.published else None,
            }
            for d in all_docs[:limit]
        ]

    return ok(docs)


@router.get("/api/vault/doc/{doc_id:path}")
def vault_doc_detail(
    doc_id: str,
    request: Request,
) -> dict[str, object]:
    """vault 단일 문서 내용."""
    from veristar.vault.store import VaultStore

    store = VaultStore("vault")
    doc = store.read(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"vault doc not found: {doc_id}")
    return ok(
        {
            "id": doc.id,
            "title": doc.title,
            "content": doc.content,
            "source_type": doc.source_type,
            "source_url": doc.source_url,
            "confidence": doc.confidence,
            "license": doc.license,
            "sensitive": doc.sensitive,
            "published": str(doc.published) if doc.published else None,
        }
    )


# --- HTMX UI ---


@router.get("/api/qa")
def api_qa(
    q: str = Query(min_length=1),
    entity_id: str | None = Query(default=None),
    repo: GraphRepository = Depends(get_repo),
) -> dict[str, object]:
    """그래프 근거 자연어 Q&A. OFFICIAL 사실만 사용, 추론 없음."""
    result = answer_question(repo, q, entity_id=entity_id)
    return ok(
        {
            "question": result.question,
            "answer": result.answer,
            "grounded_in_count": len(result.grounded_in),
            "model": result.model_used,
        }
    )


@router.get("/ui/qa", response_class=HTMLResponse)
def ui_qa(
    request: Request,
    q: str = Query(default=""),
    repo: GraphRepository = Depends(get_repo),
) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    result = answer_question(repo, q) if q.strip() else None
    return templates.TemplateResponse(request, "qa.html", {"q": q, "result": result})


@router.get("/ui/entities/{entity_id:path}/summary", response_class=HTMLResponse)
def ui_summary(
    request: Request,
    entity_id: str,
    repo: GraphRepository = Depends(get_repo),
) -> HTMLResponse:
    result = generate_summary(repo, entity_id)
    if result is None:
        return HTMLResponse("<p>엔티티를 찾을 수 없습니다.</p>", status_code=404)
    lines = result.timeline_text.split("\n") if result.timeline_text else []
    html = f"<strong>{result.summary_text}</strong>"
    if lines:
        html += (
            "<ul style='margin:0.5rem 0 0 1rem;'>"
            + "".join(f"<li>{ln}</li>" for ln in lines[:15])
            + "</ul>"
        )
    note = f"출처 기반 사실 {result.statement_count}건 · OFFICIAL 등급만 · 추론 없음"
    html += f"<p class='meta' style='margin-top:0.5rem;'>{note}</p>"
    return HTMLResponse(html)


@router.get("/ui/graph", response_class=HTMLResponse)
def ui_graph(request: Request) -> HTMLResponse:
    """D3.js Force Graph 그래프 탐색기."""
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "graph.html", {})


@router.get("/ui/vault", response_class=HTMLResponse)
def ui_vault(request: Request) -> HTMLResponse:
    """vault 문서 브라우저."""
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "vault.html", {})


@router.get("/ui/vault/doc", response_class=HTMLResponse)
def ui_vault_doc(
    request: Request,
    id: str = Query(default=""),
) -> HTMLResponse:
    """vault 단일 문서 렌더링 (HTMX partial)."""
    if not id:
        return HTMLResponse("<p class='meta'>문서를 선택하세요.</p>")
    import re

    from veristar.vault.store import VaultStore

    store = VaultStore("vault")
    doc = store.read(id)
    if doc is None:
        return HTMLResponse("<p class='meta'>문서를 찾을 수 없습니다.</p>", status_code=404)

    confidence_color = {"high": "#2e7d32", "medium": "#e65100", "low": "#c62828"}.get(
        doc.confidence, "#666"
    )
    # Markdown을 간단히 HTML로 변환
    content_html = doc.content
    content_html = re.sub(r"^#{4} (.+)$", r"<h4>\1</h4>", content_html, flags=re.MULTILINE)
    content_html = re.sub(r"^#{3} (.+)$", r"<h3>\1</h3>", content_html, flags=re.MULTILINE)
    content_html = re.sub(r"^#{2} (.+)$", r"<h2>\1</h2>", content_html, flags=re.MULTILINE)
    content_html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", content_html, flags=re.MULTILINE)
    content_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content_html)
    content_html = content_html.replace("\n\n", "</p><p>").replace("\n", "<br>")
    content_html = f"<p>{content_html}</p>"

    html = f"""
<div style="padding:0.5rem 0">
  <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap;margin-bottom:0.6rem">
    <span style="font-size:0.7rem;background:#eee;padding:2px 6px;border-radius:4px">
      {doc.source_type}</span>
    <span style="font-size:0.7rem;color:{confidence_color};font-weight:600">{doc.confidence}</span>
    {"<span style='font-size:0.7rem;color:#c62828'>🔒 민감</span>" if doc.sensitive else ""}
    {f'<span style="font-size:0.7rem;color:#888">{doc.published}</span>' if doc.published else ""}
  </div>
  <a href="{doc.source_url}" target="_blank"
     style="font-size:0.75rem;color:var(--accent);word-break:break-all">{doc.source_url}</a>
  {
        f'<div style="font-size:0.7rem;color:#888;margin-top:2px">라이선스: {doc.license}</div>'
        if doc.license
        else ""
    }
  <hr style="margin:0.6rem 0;border:none;border-top:1px solid var(--line)">
  <div style="font-size:0.82rem;line-height:1.6;max-height:60vh;overflow-y:auto">
    {content_html[:8000]}
  </div>
</div>"""
    return HTMLResponse(html)


@router.get("/", response_class=HTMLResponse)
def ui_index(request: Request) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "index.html", {})


@router.get("/ui/search", response_class=HTMLResponse)
def ui_search(
    request: Request,
    q: str = Query(default=""),
    repo: GraphRepository = Depends(get_repo),
) -> HTMLResponse:
    results = repo.search_entities(q) if q.strip() else []
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "_results.html", {"results": results, "q": q})


@router.get("/ui/entities/{entity_id:path}", response_class=HTMLResponse)
def ui_entity(
    request: Request,
    entity_id: str,
    repo: GraphRepository = Depends(get_repo),
    filt: StatementFilter = Depends(statement_filter),
) -> HTMLResponse:
    detail = entity_detail(repo, entity_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"entity not found: {entity_id}")
    views = timeline(repo, entity_id, filt)
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "entity.html",
        {"detail": detail, "views": views, "predicates": list(Predicate), "grades": list(Grade)},
    )
