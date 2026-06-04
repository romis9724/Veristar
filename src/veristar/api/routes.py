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
def health(
    request: Request, repo: GraphRepository = Depends(get_repo)
) -> dict[str, object]:
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
