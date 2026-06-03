# api — query API + HTMX 탐색 UI (M6a)

읽기전용 FastAPI 표면. `graph` 저장소·조회 위에 올라간다. 계획: [`docs/plans/m6a-query-api-plan.md`](../../../docs/plans/m6a-query-api-plan.md).

- `app.py` — 앱 팩토리(`create_app(repo)` / `create_default_app`, 시드는 `VERISTAR_SEED_PATH`)
- `routes.py` — JSON API(`/api/...`) + HTMX UI(`/`, `/ui/...`). 모든 statement에 출처 등급 부착
- `schemas.py` — 응답 엔벨로프 + 도메인→DTO
- `templates/` — Jinja2 + HTMX (출처·등급 전면 노출, Swiss/에디토리얼)

JSON 엔드포인트: `GET /api/health` · `/api/entities?q=` · `/api/entities/{id}` · `/{id}/statements` · `/{id}/timeline` · `/{id}/neighbors` (필터: `grade`·`predicate`·`status`·`from`·`to`).

기동:
```bash
uvicorn --factory veristar.api.app:create_default_app --port 8000
```
원칙: 읽기 전용. 생성/편집 없음. (`CLAUDE.md` §4)
