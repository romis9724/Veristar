"""FastAPI 앱 팩토리 + 백그라운드 시드 자동 갱신.

저장소를 주입해 앱을 만든다(테스트는 픽스처 저장소 주입). 운영은 환경변수
VERISTAR_SEED_PATH(기본 data/seed/wikidata_seed.json)에서 시드를 로드한다.

시드 자동 갱신(VERISTAR_REFRESH_INTERVAL_HOURS > 0):
- 앱 lifespan 백그라운드 태스크로 주기적으로 갱신·병합
- 완료 후 app.state.repo를 hot-reload(진행 중 요청은 기존 저장소 그대로 서빙)
- config/roots.txt → scripts/refresh_seed.sh 와 동일한 seed.main() 호출

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
            # blocking I/O → 별도 스레드에서 실행(이벤트 루프 차단 방지)
            await asyncio.get_event_loop().run_in_executor(
                None,
                _do_refresh,
                seed_path,
                roots_path,
                max_entities,
            )
            # 갱신된 파일로 저장소 교체
            new_repo = InMemoryGraphRepository.from_path(seed_path)
            app.state.repo = new_repo
            s = new_repo.stats()
            logger.info(
                "시드 갱신 완료: 엔티티 %d · statement %d · 소스 %d",
                s["entities"],
                s["statements"],
                s["sources"],
            )
        except Exception as exc:
            logger.error("시드 갱신 실패(다음 주기에 재시도): %s", exc)


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
        logger.info(
            "시드 자동 갱신 활성: %.1f시간 간격 (VERISTAR_REFRESH_INTERVAL_HOURS=%.1f)",
            interval,
            interval,
        )
        task = asyncio.create_task(_seed_refresh_loop(app, seed_path, interval))
    else:
        logger.info("시드 자동 갱신 비활성 (VERISTAR_REFRESH_INTERVAL_HOURS=0)")
        task = None
    try:
        yield
    finally:
        if task:
            task.cancel()


def create_app(repo: InMemoryGraphRepository) -> FastAPI:
    app = FastAPI(title="Veristar Query API", version="0.1.0")
    app.state.repo = repo
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    from .routes import router  # 순환참조 회피

    app.include_router(router)
    return app


def build_default_repo() -> InMemoryGraphRepository:
    path = os.environ.get("VERISTAR_SEED_PATH", _DEFAULT_SEED)
    return InMemoryGraphRepository.from_path(path)


def create_default_app() -> FastAPI:
    repo = build_default_repo()
    app = FastAPI(title="Veristar Query API", version="0.1.0", lifespan=_lifespan)
    app.state.repo = repo
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    from .routes import router

    app.include_router(router)
    return app
