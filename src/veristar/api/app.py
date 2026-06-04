"""FastAPI 앱 팩토리 + 저장소 선택 + 백그라운드 시드 자동 갱신.

저장소 선택 우선순위:
  1. PostgreSQL (DATABASE_URL 환경변수 + 연결 가능할 때) → PostgreSQLGraphRepository
  2. InMemory JSONL 폴백 (VERISTAR_SEED_PATH)

PostgreSQL 모드에서는 get_repo() Depends가 요청마다 커넥션을 열고 닫는다.
InMemory 모드에서는 app.state.repo를 공유한다.

시드 자동 갱신(VERISTAR_REFRESH_INTERVAL_HOURS > 0):
- PostgreSQL 모드: JSONL 갱신 후 pg migrate 동기화
- InMemory 모드: JSONL 갱신 후 in-memory hot-reload

    uvicorn --factory veristar.api.app:create_default_app
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from veristar.graph import InMemoryGraphRepository

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
_DEFAULT_SEED = "data/seed/wikidata_seed.json"
_DEFAULT_ROOTS = "config/roots.txt"
_DEFAULT_MAX = 80


def _refresh_interval_hours() -> float:
    """VERISTAR_REFRESH_INTERVAL_HOURS 환경변수. 0이면 자동 갱신 비활성."""
    try:
        return float(os.environ.get("VERISTAR_REFRESH_INTERVAL_HOURS", "24"))
    except ValueError:
        return 24.0


async def _seed_refresh_loop(app: FastAPI, seed_path: str, interval_hours: float) -> None:
    """주기적으로 Wikidata 시드를 갱신·병합하고 저장소를 hot-reload한다."""
    interval_sec = interval_hours * 3600
    roots_path = os.environ.get("VERISTAR_ROOTS_FILE", _DEFAULT_ROOTS)
    max_entities = int(os.environ.get("VERISTAR_MAX", str(_DEFAULT_MAX)))

    while True:
        await asyncio.sleep(interval_sec)
        logger.info("자동 시드 갱신 시작 (interval=%.1fh, roots=%s)", interval_hours, roots_path)
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, _do_refresh, seed_path, roots_path, max_entities,
            )
            if app.state.use_postgres:
                # PostgreSQL 모드: JSONL → PG 동기화
                await asyncio.get_event_loop().run_in_executor(None, _pg_sync, seed_path)
                logger.info("PostgreSQL 시드 갱신 완료")
            else:
                # InMemory 모드: 저장소 hot-reload
                new_repo = InMemoryGraphRepository.from_path(seed_path)
                app.state.repo = new_repo
                s = new_repo.stats()
                logger.info(
                    "시드 갱신 완료: 엔티티 %d · statement %d · 소스 %d",
                    s["entities"], s["statements"], s["sources"],
                )
        except Exception as exc:
            logger.error("시드 갱신 실패(다음 주기에 재시도): %s", exc)


def _pg_sync(seed_path: str) -> None:
    """JSONL → PostgreSQL 동기화 (PostgreSQL 모드 자동 갱신 후 호출)."""
    from pgvector.psycopg import register_vector  # type: ignore[import-untyped]

    from veristar.db.connection import get_conn, is_available
    from veristar.db.migrate import migrate_graph
    from veristar.db.pg_repository import PostgreSQLGraphRepository

    if not is_available():
        return
    try:
        with get_conn() as conn:
            register_vector(conn)
            repo = PostgreSQLGraphRepository(conn)  # type: ignore[arg-type]
            migrate_graph(repo, Path(seed_path))
        logger.info("PostgreSQL 동기화 완료")
    except Exception as exc:
        logger.warning("PostgreSQL 동기화 실패: %s", exc)


def _do_refresh(seed_path: str, roots_path: str, max_entities: int) -> None:
    """동기: seed.main()과 동일한 수집·병합 로직."""
    from datetime import datetime

    from veristar.graph import merge
    from veristar.ingest.wikidata.client import HttpWikidataClient
    from veristar.ingest.wikidata.seed import build_seed, read_roots_file, write_seed
    from veristar.ontology.graph import load_graph

    roots = read_roots_file(roots_path) if Path(roots_path).exists() else []
    if not roots:
        logger.warning("roots 파일 없음 또는 비어 있음: %s", roots_path)
        return

    client = HttpWikidataClient()
    try:
        incoming = build_seed(
            client,
            roots,
            retrieved_at=datetime.now(),
            require_reference=False,  # allow-unreferenced
            max_entities=max_entities,
        )
    finally:
        client.close()

    p = Path(seed_path)
    if p.exists():
        base = load_graph(p)
        doc, report = merge(base, incoming)
        logger.info("병합 결과: %s", report.summary())
    else:
        doc = incoming

    write_seed(doc, p)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    interval = _refresh_interval_hours()
    seed_path = os.environ.get("VERISTAR_SEED_PATH", _DEFAULT_SEED)

    if interval > 0:
        logger.info("시드 자동 갱신 활성: %.1fh (VERISTAR_REFRESH_INTERVAL_HOURS)", interval)
        task = asyncio.create_task(_seed_refresh_loop(app, seed_path, interval))
    else:
        logger.info("시드 자동 갱신 비활성")
        task = None
    try:
        yield
    finally:
        if task:
            task.cancel()


def create_app(repo: InMemoryGraphRepository) -> FastAPI:
    """테스트·커스텀 저장소 주입용 (InMemory)."""
    app = FastAPI(title="Veristar Query API", version="0.1.0")
    app.state.repo = repo
    app.state.use_postgres = False
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    from .routes import router
    app.include_router(router)
    return app


def create_default_app() -> FastAPI:
    """운영 진입점 — PostgreSQL 우선, InMemory 폴백."""
    from veristar.db.connection import is_available

    app = FastAPI(title="Veristar Query API", version="0.1.0", lifespan=_lifespan)
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    if is_available():
        logger.info("저장소: PostgreSQL (DATABASE_URL)")
        app.state.use_postgres = True
        app.state.repo = None  # routes.py의 get_repo()가 요청마다 커넥션 생성
    else:
        seed_path = os.environ.get("VERISTAR_SEED_PATH", _DEFAULT_SEED)
        logger.info("저장소: InMemory JSONL (%s)", seed_path)
        app.state.use_postgres = False
        app.state.repo = InMemoryGraphRepository.from_path(seed_path)

    from .routes import router
    app.include_router(router)
    return app
