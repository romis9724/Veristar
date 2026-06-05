"""엔드포인트 — JSON API(/api) + HTMX UI(/, /ui).

읽기 전용. 모든 statement 응답에 출처(등급)를 함께 싣는다.

저장소 선택:
  - app.state.use_postgres=True  → 요청마다 PostgreSQLGraphRepository (psycopg 커넥션)
  - app.state.use_postgres=False → app.state.repo (InMemoryGraphRepository)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from dataclasses import field as dc_field
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


# --- Pipeline 상태 저장소 + 브로드캐스트 ---
# 서버 메모리에 파이프라인 로그를 보관 + 여러 SSE 구독자에게 동시 전달.
# 브라우저 페이지 이탈 후 재접속해도 기존 로그 복원 + 새 메시지 계속 수신.


@dataclass
class _PipelineState:
    task_id: str
    status: str = "idle"   # idle | running | done | error
    logs: list[dict[str, object]] = dc_field(default_factory=list)
    summary: dict[str, object] = dc_field(default_factory=dict)
    # 활성 SSE 구독자 큐 목록 — put() 호출 시 전부에 브로드캐스트
    subscribers: list[asyncio.Queue[dict[str, object]]] = dc_field(default_factory=list)


_pipeline: _PipelineState = _PipelineState(task_id="")


@router.get("/api/pipeline/status")
def pipeline_status() -> dict[str, object]:
    """현재 파이프라인 상태 반환."""
    return ok({
        "task_id": _pipeline.task_id,
        "status": _pipeline.status,
        "log_count": len(_pipeline.logs),
        "summary": _pipeline.summary,
    })


@router.get("/api/pipeline/logs")
def pipeline_logs() -> dict[str, object]:
    """전체 로그 반환 (재접속 시 화면 복원용)."""
    return ok({
        "task_id": _pipeline.task_id,
        "status": _pipeline.status,
        "logs": _pipeline.logs,
        "summary": _pipeline.summary,
    })


# --- Graph / Tree / Vault API ---


# bge-m3 cosine 분포: 관련 0.6~0.78 / 무관 0.45 이하 → 0.5 경계가 변별점
_RAG_SIM_THRESHOLD = 0.5       # 기본 유사도 임계값 (이 미만은 무관련로 제외)
_RAG_UNVERIFIED_WEIGHT = 0.5   # 미검증 문서의 점수 가중치
_CONF_WEIGHTS = {
    "high": 1.0, "medium": 0.85, "low": 0.6, "unverified": _RAG_UNVERIFIED_WEIGHT
}
# 소스 유형별 품질 가중치 — Wikipedia 우선, 나무위키 LOW 후순위
_SRC_WEIGHTS = {
    "wikipedia": 1.2,
    "news": 1.0,
    "namuwiki": 0.8,
    "youtube": 0.9,
    "instagram": 0.85,
    "twitter": 0.85,
}
_CONF_WEIGHTS = {
    "high": 1.0, "medium": 0.85, "low": 0.6, "unverified": _RAG_UNVERIFIED_WEIGHT
}


@router.get("/api/search/rag")
def rag_search(
    q: str = Query(min_length=1),
    confidence: list[str] | None = Query(default=None),
    source_type: list[str] | None = Query(default=None),
    grade: list[Grade] | None = Query(default=None),
    include_unverified: bool = Query(default=False, description="미검증 문서 포함 여부"),
    include_sensitive: bool = Query(default=False),
    sim_threshold: float = Query(default=_RAG_SIM_THRESHOLD, ge=0.0, le=1.0),
    limit: int = Query(default=20, ge=1, le=100),
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, object]:
    """RAG 통합 검색 — vault_docs(벡터 + 유사도 임계값) + 엔티티(텍스트)를 모두 검색.

    관련성 기준:
      - cosine similarity >= sim_threshold(기본 0.82) 만 포함
      - 미검증(unverified) 문서는 기본 제외 (include_unverified=true 시 포함)
      - confidence 가중치: high×1.0 / medium×0.85 / low×0.6 / unverified×0.3

    파라미터:
      confidence: high|medium|low (복수 가능, 기본=high+medium+low)
      source_type: wikipedia|namuwiki|news (복수 가능)
      include_unverified: 미검증 포함 (기본 false)
      sim_threshold: 유사도 임계값 (기본 0.82)
    """
    from veristar.db.connection import is_available

    # 기본 confidence 필터: unverified 제외
    effective_conf = set(confidence) if confidence else {"high", "medium", "low"}
    if include_unverified:
        effective_conf.add("unverified")

    results: list[dict[str, object]] = []

    # ── 1. 벡터 검색: vault_docs (PostgreSQL 모드일 때)
    if is_available() and getattr(request.app.state, "use_postgres", False):
        from pgvector.psycopg import register_vector  # type: ignore[import-untyped]

        from veristar.db.connection import get_conn
        from veristar.db.vector_store import VectorStore

        conn = get_conn()
        register_vector(conn)
        try:
            vs = VectorStore(conn)
            src_filter = source_type[0] if source_type and len(source_type) == 1 else None

            # 임계값 이상 전부 가져오고 후처리
            vault_results = vs.search_vault_docs(q, limit=limit * 3, source_type=src_filter)
            for vr in vault_results:
                # 민감 문서 필터 (CLAUDE.md §4-5: 생성·API 노출 단계에서 차단)
                if not include_sensitive and getattr(vr, "sensitive", False):
                    continue
                # confidence 필터
                if vr.confidence not in effective_conf:
                    continue
                # source_type 복수 필터
                if source_type and vr.source_type not in source_type:
                    continue
                # 유사도 × confidence 가중치 × source 가중치 = 최종 점수
                # → Wikipedia/HIGH가 나무위키/LOW보다 상위 노출
                conf_w = _CONF_WEIGHTS.get(vr.confidence, 0.5)
                src_w = _SRC_WEIGHTS.get(vr.source_type, 1.0)
                final_score = vr.similarity * conf_w * src_w
                # 임계값 미만 제외 — confidence와 무관하게 동일 적용
                # (bge-m3는 unverified 문서도 관련성 자체는 정확히 측정)
                if vr.similarity < sim_threshold:
                    continue
                results.append({
                    "type": "vault_doc",
                    "id": vr.id,
                    "title": vr.title,
                    "source_type": vr.source_type,
                    "source_url": vr.source_url,
                    "confidence": vr.confidence,
                    "similarity": round(vr.similarity, 4),
                    "score": round(final_score, 4),
                    "snippet": vr.content[:300],
                })
        finally:
            conn.close()
    else:
        # InMemory 폴백: vault 파일시스템 검색
        from veristar.vault.store import VaultStore as VStore
        store = VStore("vault")
        all_docs = store.list_docs()
        # 간단한 키워드 매칭
        q_lower = q.lower()
        for doc in all_docs:
            if q_lower in doc.title.lower() or q_lower in doc.content[:1000].lower():
                if confidence and doc.confidence not in confidence:
                    continue
                if source_type and doc.source_type not in source_type:
                    continue
                results.append({
                    "type": "vault_doc",
                    "id": doc.id,
                    "title": doc.title,
                    "source_type": doc.source_type,
                    "source_url": doc.source_url,
                    "confidence": doc.confidence,
                    "similarity": 0.0,
                    "snippet": doc.content[:300],
                })

    # ── 2. 엔티티 검색 (텍스트 기반, 항상 실행)
    repo_gen = get_repo(request)
    repo = next(repo_gen)
    try:
        entities = repo.search_entities(q, limit=min(limit, 10))
        for e in entities:
            results.append({
                "type": "entity",
                "id": e.id,
                "name": e.name,
                "entity_type": str(getattr(e, "type", "")),
                "aliases": list(e.aliases[:3]),
                "similarity": 1.0,  # 이름 직접 매칭
                "url": f"/ui/entities/{e.id}",
            })
    finally:
        import contextlib
        with contextlib.suppress(StopIteration):
            next(repo_gen)

    # 최종 점수(유사도 × confidence 가중치) 내림차순 정렬
    results.sort(key=lambda x: float(x.get("score", x.get("similarity", 0))), reverse=True)
    return ok({
        "query": q,
        "total": len(results),
        "results": results[:limit],
        "filters": {
            "confidence": confidence,
            "source_type": source_type,
            "grade": [str(g) for g in grade] if grade else None,
            "include_sensitive": include_sensitive,
        },
    })


@router.get("/api/pipeline/stream")  # pragma: no cover
async def pipeline_stream(
    request: Request,
    sources: str = Query(default="wikipedia,namuwiki,news"),
    limit: int = Query(default=50, ge=1, le=500),
    steps: str = Query(default="collect,verify,sync,migrate"),
) -> object:
    """데이터 수집·검증·동기화 파이프라인을 실행하고 SSE로 진행 상황을 스트리밍한다.

    서버 메모리(_pipeline)에 로그를 보관해 페이지 이탈 후 재접속해도 전체 로그 복원 가능.
    이미 실행 중이면 새 실행 없이 현재 로그만 스트리밍.
    """
    from fastapi.responses import StreamingResponse

    global _pipeline  # noqa: PLW0603

    loop = asyncio.get_event_loop()

    # ── 구독자 등록 헬퍼 ────────────────────────────────────────────────────
    async def _stream_to_client() -> AsyncIterator[str]:
        """기존 로그 재생 후 신규 메시지를 브로드캐스트로 수신.

        레이스 컨디션 방지:
          1. 구독자 큐 먼저 등록
          2. 그 시점까지의 로그를 replay_end 기준으로 재생
          3. 이후 큐에서 신규 메시지 수신
        """
        sub_q: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        _pipeline.subscribers.append(sub_q)
        replay_end = len(_pipeline.logs)  # 등록 시점 스냅샷
        try:
            # 기존 로그 재생
            for msg in _pipeline.logs[:replay_end]:
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            # 신규 메시지 수신
            while True:
                msg = await sub_q.get()
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                if msg.get("type") == "done":
                    break
        finally:
            with contextlib.suppress(ValueError):
                _pipeline.subscribers.remove(sub_q)

    # 이미 실행 중이면 구독만 (중복 실행 방지)
    if _pipeline.status == "running":
        return StreamingResponse(
            _stream_to_client(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # 완료/오류 상태면 기존 로그를 한번만 재생
    if _pipeline.status in ("done", "error") and _pipeline.logs:
        async def _replay_once() -> AsyncIterator[str]:
            for msg in list(_pipeline.logs):
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
        return StreamingResponse(_replay_once(), media_type="text/event-stream",
                                  headers={"Cache-Control": "no-cache"})

    # 새 파이프라인 시작
    task_id = str(uuid.uuid4())[:8]
    _pipeline.task_id = task_id
    _pipeline.status = "running"
    _pipeline.logs = []
    _pipeline.summary = {}
    _pipeline.subscribers = []

    def put(msg: dict[str, object]) -> None:
        _pipeline.logs.append(msg)
        # 모든 구독자에게 브로드캐스트
        for sub_q in list(_pipeline.subscribers):
            loop.call_soon_threadsafe(sub_q.put_nowait, msg)

    def _run() -> None:
        global _pipeline  # noqa: PLW0603
        step_list = [s.strip() for s in steps.split(",")]
        src_list = [s.strip() for s in sources.split(",")]
        put({"type": "header", "msg": f"파이프라인 시작 — {', '.join(step_list)}"})

        # ── 1. 멀티소스 수집 ────────────────────────────────────────────────
        if "collect" in step_list:
            put({"type": "step", "name": "멀티소스 수집", "icon": "📥", "status": "running",
                 "detail": f"소스: {sources} | 한도: {limit}건"})
            try:
                from veristar.ingest.collectors.runner import load_targets
                from veristar.vault.store import VaultStore

                store = VaultStore("vault")
                targets, db_mode = load_targets("config/celebrities.yaml", limit=limit)
                put({"type": "log", "level": "info",
                     "msg": f"  수집 대상 {len(targets)}건 ({('DB' if db_mode else 'YAML')} 모드)"})

                total_saved = total_skip = 0
                for i, target in enumerate(targets, 1):
                    name = target.get("name", "?")
                    put({"type": "progress", "current": i, "total": len(targets),
                         "label": name})
                    for src in src_list:
                        try:
                            if src == "wikipedia":
                                from veristar.ingest.collectors.wikipedia import WikipediaCollector
                                with WikipediaCollector(store) as c:
                                    r = c.collect(name)
                                    total_saved += r.saved
                                    total_skip += r.skipped
                            elif src == "namuwiki":
                                from veristar.ingest.collectors.namuwiki import NamuWikiCollector
                                namu_title = target.get("namu_title") or name
                                with NamuWikiCollector(store) as c:
                                    r = c.collect(namu_title)
                                    total_saved += r.saved
                                    total_skip += r.skipped
                        except Exception as exc:
                            put({"type": "log", "level": "warn",
                                 "msg": f"  [{src}] {name}: {exc!s:.60}"})

                # 뉴스 수집 (피드별)
                if "news" in src_list:
                    from veristar.ingest.collectors.news import NewsCollector
                    from veristar.ingest.news.rss import load_feed_configs
                    feeds = load_feed_configs("config/news_feeds.yaml")
                    with NewsCollector(store) as c:
                        for cfg in feeds:
                            put({"type": "log", "level": "info",
                                 "msg": f"  뉴스 피드: {cfg.name}"})
                            r = c.collect(cfg.url, feed_name=cfg.name, source_type=cfg.source_type)
                            total_saved += r.saved

                put({"type": "step_done", "name": "멀티소스 수집",
                     "msg": f"저장 {total_saved}건 / 스킵 {total_skip}건"})
            except Exception as exc:
                put({"type": "step_error", "name": "멀티소스 수집", "msg": str(exc)})

        # ── 2. LLM 검증 ─────────────────────────────────────────────────────
        if "verify" in step_list:
            put({"type": "step", "name": "LLM 검증", "icon": "🔍", "status": "running",
                 "detail": "unverified 문서를 HIGH/MEDIUM/LOW로 분류"})
            try:
                from veristar.vault.store import VaultStore
                from veristar.verify.pipeline import VerifyPipeline

                store = VaultStore("vault")
                unverified = store.list_unverified()
                put({"type": "log", "level": "info",
                     "msg": f"  미검증 문서 {len(unverified)}건 처리"})

                pipeline = VerifyPipeline(store)
                for i, doc in enumerate(unverified, 1):
                    put({"type": "progress", "current": i, "total": len(unverified),
                         "label": doc.title[:40]})
                    pipeline.run([doc])

                vs = store.stats()
                put({"type": "step_done", "name": "LLM 검증",
                     "msg": (f"HIGH {vs.get('verified_high', 0)}건 | "
                             f"미검증 {vs.get('unverified', 0)}건 남음")})
            except Exception as exc:
                put({"type": "step_error", "name": "LLM 검증", "msg": str(exc)})

        # ── 3. 그래프 승격 ──────────────────────────────────────────────────
        if "sync" in step_list:
            put({"type": "step", "name": "그래프 승격", "icon": "📊", "status": "running",
                 "detail": "HIGH vault docs → JSONL 그래프"})
            try:
                from pathlib import Path

                from veristar.vault.store import VaultStore
                from veristar.verify.graph_sync import sync_high_to_graph

                report = sync_high_to_graph(
                    VaultStore("vault"),
                    Path("data/seed/wikidata_seed.json"),
                )
                put({"type": "step_done", "name": "그래프 승격",
                     "msg": (f"statement +{report.new_statements}건 | "
                             f"source +{report.new_sources}건")})
            except Exception as exc:
                put({"type": "step_error", "name": "그래프 승격", "msg": str(exc)})

        # ── 4. PostgreSQL 동기화 ────────────────────────────────────────────
        if "migrate" in step_list:
            put({"type": "step", "name": "PostgreSQL 동기화", "icon": "🐘", "status": "running",
                 "detail": "JSONL + vault → PostgreSQL + 임베딩"})
            try:
                from pathlib import Path

                from veristar.db.migrate import run_migration

                report = run_migration(
                    Path("data/seed/wikidata_seed.json"),
                    Path("vault"),
                    embed=True,
                )
                put({"type": "step_done", "name": "PostgreSQL 동기화",
                     "msg": (f"entities {report.entities} | statements {report.statements} | "
                             f"vault_docs {report.vault_docs} | "
                             f"임베딩 {report.entity_embeddings + report.vault_embeddings}건")})
            except Exception as exc:
                put({"type": "step_error", "name": "PostgreSQL 동기화", "msg": str(exc)})

        # ── 완료 ───────────────────────────────────────────────────────────
        from veristar.vault.store import VaultStore
        vs = VaultStore("vault").stats()
        summary = {
            "vault_total": vs["total"],
            "verified_high": vs["verified_high"],
            "unverified": vs["unverified"],
        }
        _pipeline.summary = summary
        _pipeline.status = "done"
        put({"type": "done", "summary": summary})

    # 백그라운드 스레드에서 파이프라인 실행 후 구독자 스트림으로 서빙
    threading.Thread(target=_run, daemon=True).start()
    return StreamingResponse(
        _stream_to_client(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/ui/collect", response_class=HTMLResponse)
def ui_collect(request: Request) -> HTMLResponse:
    """데이터 수집·동기화 파이프라인 실행 + 실시간 진행 화면."""
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "collect.html", {})


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
    # Markdown → HTML 변환 (XSS 방지: 먼저 이스케이프 후 변환)
    import html as _html_mod
    safe = _html_mod.escape(doc.content)  # < > & " → 엔티티로 이스케이프
    content_html = re.sub(r"^#{4} (.+)$", r"<h4>\1</h4>", safe, flags=re.MULTILINE)
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
