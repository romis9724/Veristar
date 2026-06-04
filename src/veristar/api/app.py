"""FastAPI 앱 팩토리.

저장소를 주입해 앱을 만든다(테스트는 픽스처 저장소 주입). 운영은 환경변수
VERISTAR_SEED_PATH(기본 data/seed/wikidata_seed.json)에서 시드를 로드한다:

    uvicorn --factory veristar.api.app:create_default_app
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from veristar.graph import InMemoryGraphRepository

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
_DEFAULT_SEED = "data/seed/wikidata_seed.json"


def create_app(repo: InMemoryGraphRepository) -> FastAPI:
    app = FastAPI(title="Veristar Query API", version="0.1.0")
    app.state.repo = repo
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    # htmx 등 정적 자산은 self-host (CDN 의존·차단 회피, 오프라인·CSP 친화)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    from .routes import router  # 순환참조 회피

    app.include_router(router)
    return app


def build_default_repo() -> InMemoryGraphRepository:
    path = os.environ.get("VERISTAR_SEED_PATH", _DEFAULT_SEED)
    return InMemoryGraphRepository.from_path(path)


def create_default_app() -> FastAPI:
    return create_app(build_default_repo())
