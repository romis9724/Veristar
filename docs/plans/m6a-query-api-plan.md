# M6a 구현 계획 — 읽기전용 query API + 최소 탐색 UI

> 목표: M2 Wikidata 시드(`data/seed/*.json`) 위에서 **구조적 그래프 탐색**을 제공한다. 엔티티 검색 → 관계·연표·**출처 등급** 탐색. 읽기 전용. 1차 출시 슬라이스.
>
> 근거: `docs/service-design.md` §5(query 설계)·§8(DoD). Karpathy `query` 연산 대응. 방법론: TDD.

---

## 0. 핵심 원칙

1. **레이어드 + Repository 패턴.** 저장소(현재 JSON, 후일 Neo4j) ↔ query 서비스 ↔ API ↔ UI. 저장소는 Protocol 뒤에 둬 교체 가능하게(`CLAUDE.md` §7, patterns).
2. **출처 등급을 1급으로 노출.** 모든 statement 응답에 source(등급·url·source_type)를 함께 싣는다 — Veristar의 차별점.
3. **읽기 전용.** 변경 엔드포인트 없음.
4. **네트워크 없는 테스트.** 저장소는 픽스처 GraphDocument, API는 FastAPI TestClient.

## 1. 모듈 구조

```
src/veristar/
├── graph/                      # 저장소 + 조회 (파이프라인 [4] + query)
│   ├── repository.py           # GraphRepository(Protocol) + InMemoryGraphRepository
│   ├── filters.py              # StatementFilter (grade·status·predicate·기간)
│   └── queries.py              # search·detail·statements·timeline·neighbors
└── api/                        # FastAPI 표면
    ├── app.py                  # 앱 생성 + 저장소 의존성 주입
    ├── schemas.py              # 응답 엔벨로프(success/data/error)
    ├── routes.py               # 엔드포인트
    └── templates/              # (UI 선택에 따라) HTMX 템플릿
```

## 2. 저장소 (graph/repository.py)

- `InMemoryGraphRepository(GraphDocument)` — M2 시드를 `load_graph()`로 읽어 인덱스 구축:
  - `by_id: dict[str, Entity]`
  - `name_index`: 이름·alias 소문자 토큰 → entity id (부분일치 검색용)
  - `out_adj`, `in_adj`: subject/object id → [Statement] (양방향 탐색)
  - `sources_by_id: dict[str, Source]`
- Repository 패턴: `GraphRepository` Protocol(get/search/statements_for/neighbors)로 추상화 → 후일 Neo4j 구현 교체.

## 3. 조회 연산 (graph/queries.py)

| 연산 | 설명 |
|---|---|
| `search(q, limit)` | 이름·alias 부분일치(대소문자 무시) → 엔티티 목록 |
| `get_entity(id)` | 엔티티 + 요약(나가는/들어오는 statement 수) |
| `statements_for(id, filter)` | 해당 엔티티의 statement(subject/object 양쪽), 필터 적용, **각 statement에 sources 부착** |
| `timeline(id, filter)` | statement를 `valid_from` 기준 시간순 정렬 |
| `neighbors(id, filter)` | 연결된 엔티티(관계 라벨 포함) |

- `StatementFilter`: grades(기본 전체)·statuses(기본 ACTIVE)·predicates·date_from·date_to. (생성용 게이트 `official_nonsensitive`와 별개 — 탐색은 등급을 *보여주되* 필터로 선택)

## 4. API (api/routes.py)

응답은 일관 엔벨로프(`{ "data": ..., "error": null }`, patterns).

| 메서드·경로 | 동작 |
|---|---|
| `GET /health` | 상태·시드 통계(엔티티/statement 수) |
| `GET /entities?q=&limit=` | 엔티티 검색 |
| `GET /entities/{id}` | 엔티티 상세 + 관계 요약 (id는 `wd:Q...` → `{id:path}`로 수용) |
| `GET /entities/{id}/statements?grade=&predicate=&status=&from=&to=` | 필터된 statement(+sources) |
| `GET /entities/{id}/timeline` | 연표 |
| `GET /entities/{id}/neighbors?grade=&predicate=` | 인접 엔티티 |

- 저장소는 앱 시작 시 1회 로드(시드 경로는 설정/env). 의존성 주입으로 테스트 시 픽스처 교체.

## 5. 최소 탐색 UI

> ✅ **프론트 스택 확정(2026-06-04): FastAPI + Jinja2 + HTMX** (무빌드·서버렌더·Python 단일 스택).

HTMX 기준 화면:
- 검색창 → 결과 목록(타입 배지)
- 엔티티 페이지: 헤더(이름·타입·alias) + 관계 테이블(predicate·상대·**등급 배지**·기간·출처 링크) + 연표 뷰
- 등급/기간/predicate 필터(서버 렌더 부분 갱신)

## 6. TDD 순서

1. `test_repository.py` — 인덱스·search·양방향 adjacency (픽스처 GraphDocument).
2. `test_queries.py` — 필터(grade/status/기간), timeline 정렬, neighbors, sources 부착.
3. `test_api.py` — TestClient로 각 엔드포인트(검색·상세·필터·연표·404·엔벨로프).
4. (UI 채택 시) 스모크: 핵심 페이지 200 + 주요 텍스트 포함.

## 7. 의존성
- `fastapi`, `uvicorn`(런), `httpx`(TestClient, 이미 있음). HTMX는 `jinja2` + CDN/정적 htmx.

## 8. 완료 기준 (DoD, service-design §8)
- [ ] 저장소가 M2 시드를 로드, 양방향 인덱스 구축.
- [ ] search / detail / statements(필터) / timeline / neighbors 조회 + 테스트.
- [ ] FastAPI 엔드포인트 + TestClient 테스트, 일관 엔벨로프.
- [ ] 모든 statement 응답에 **출처 등급** 포함.
- [ ] 최소 탐색 UI(채택 스택)로 검색→엔티티→관계·연표 탐색.
- [ ] ruff·mypy·pytest(커버리지 80%+) green.

## 9. 범위 밖
- 쓰기/편집, 자연어 Q&A(M6b), 콘텐츠 생성(M5), 뉴스(M4). 인증·배포는 1차 이후.

## 10. 열린 질문
1. ✅ **UI 프론트 스택** — FastAPI + Jinja2 + HTMX로 확정.
2. 시드 경로/로딩 설정 방식(env vs 설정파일) — 구현 시 결정.
3. `require_reference` 기본 정책 재검토(M2 발견) — 탐색 UI에서 등급으로 구분 노출하므로 보류 가능.
