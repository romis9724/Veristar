# Veristar

> 출처 등급으로 검증한 한국 연예인 지식그래프 + 안전한 콘텐츠 생성 시스템.
> *veritas*(진실) + *star*(스타).

이 문서는 Claude Code가 이 프로젝트를 다룰 때 따라야 할 **상위 규칙**이다.
세부 데이터 모델은 `docs/ontology-schema.md`, 안전 규칙은 `docs/safety-guidelines.md`,
서비스 설계는 `docs/service-design.md`를 본다.

---

## 1. 한 줄 정의

한국 연예 도메인의 엔티티(인물·그룹·소속사·작품·이벤트)와 관계를 그래프로 구조화하되,
**모든 사실에 출처와 신뢰 등급을 붙이고**, 그중 "공식 확인된" 사실만 콘텐츠 생성의 재료로 쓴다.

## 2. 차별점

연예 정보 DB는 이미 많다(나무위키, IMDb, MusicBrainz, kprofiles 등).
Veristar의 유일한 차별점은 **출처 검증(provenance)** 이다.

- 시스템은 "이게 **진실인가**"를 판정하지 않는다 (불가능·위험).
- 대신 "이게 **공식 출처에서 나왔는가**"만 판정한다 — 객관적으로 검증 가능.

이 원칙을 깨는 설계 변경은 정체성을 무너뜨리므로, 제안 전 반드시 사용자에게 확인한다.

## 3. 3-레이어 데이터 파이프라인 (2026-06-04 확정)

```
[Layer 1] raw vault (Obsidian Markdown)
    수집기 → Wikipedia·나무위키·뉴스·YouTube·SNS → vault/*.md
              ↓ LLM cross-check (veristar.verify.pipeline)
[Layer 2] knowledge graph (PostgreSQL + pgvector)
    confidence=HIGH → 그래프 승격 · Wikidata backbone 교차 확인
              ↓ GraphRepository Protocol (InMemory 또는 PostgreSQL)
[Layer 3] service API (FastAPI / HTMX)
    OFFICIAL 등급만 콘텐츠 재료 · 민감 정보 API·생성 레벨 차단
```

**정책 (2026-06-04 인터뷰 결정)**:
- 수집 대상: **한국 연예인 전반** (가수·배우·유튜버·코미디언)
- 민감 정보: raw vault에는 저장 허용 (`sensitive=true` 플래그) → 생성·API 노출 단계에서만 차단
- 검증 방식: LLM cross-check → HIGH 자동승인·MEDIUM 큐·LOW 폐기
- 나무위키: CC BY-NC-SA 2.0 KR 라벨 필수, 비상업적 조건 준수
- SNS 스크래핑: ToS 위반 위험 인지 상태 (sns_scraper.py에 경고 명시)

## 4. 절대 원칙 (Non-negotiable)

코드를 짤 때 아래는 기능이 아니라 **제약**이다. 어기는 코드는 작성하지 않는다.

1. **출처 없는 사실은 없다.** 모든 statement는 최소 1개의 source 참조가 필수. source 없는 노드/엣지는 적재 거부.
2. **등급은 출처의 성격이지 진실 여부가 아니다.** `OFFICIAL`은 "공식 발표됨"을 뜻하지 "사실로 입증됨"을 뜻하지 않는다.
3. **콘텐츠 재료는 `OFFICIAL`만.** `REPORTED`/`RUMOR`는 저장만, 생성 입력으로는 절대 넣지 않는다.
4. **생성은 재구성(reconstructive)만.** 추론형(관계 추측·평가·예측) 생성은 기본 금지.
5. **민감 정보: raw vault 저장 가능, API·생성에서 차단.** `sensitive=true`로 표시.
6. **나무위키 콘텐츠는 CC BY-NC-SA 라벨 필수.** 상업화 전 별도 검토.

## 5. 콘텐츠 생성: 허용 / 금지

| 유형 | 정의 | 허용? |
|---|---|---|
| 재구성형 | OFFICIAL 사실의 요약·정리·연표화·번역. 새 정보 추가 없음 | ✅ |
| 추론형 | 관계 추측·미래 예측·평가·해석 추가 | ❌ |

판단 기준: **출력에 입력 statement에 없던 사실이 새로 생겼는가?** 생기면 차단.

## 6. 디렉토리 구조

```
veristar/
├── CLAUDE.md                      # (이 파일) 상위 규칙
├── README.md
├── docker-compose.yml             # PostgreSQL 16 + pgvector (포트 5433)
├── config/
│   ├── roots.txt                  # Wikidata 루트 QID
│   │                              # (수집 대상은 PostgreSQL collection_targets 테이블)
│   └── news_feeds.yaml            # RSS 피드 설정
├── docs/
│   ├── ontology-schema.md         # 엔티티·관계·출처·vault 모델
│   ├── safety-guidelines.md       # 법무·윤리 가드레일
│   └── service-design.md         # 서비스 설계 전체
├── pyproject.toml                 # 패키지·의존성·ruff/mypy/pytest
├── src/veristar/
│   ├── ontology/                  # M1: 타입 + validation
│   ├── ingest/
│   │   ├── wikidata/              # M2: Wikidata 시드 수집기
│   │   │   ├── seed.py            #   루트 QID BFS 확장 → JSONL 그래프
│   │   │   ├── sparql.py          #   WDQS SPARQL 한국 연예인 대량 발견
│   │   │   └── discover.py        #   SPARQL → collection_targets 적재 CLI
│   │   ├── wikipedia/             # Wikipedia 별칭 보완 (alias_supplement)
│   │   ├── collectors/            # 멀티소스 수집기
│   │   │   ├── base.py            #   AbstractCollector
│   │   │   ├── wikipedia.py       #   Wikipedia 전문 (CC BY-SA 4.0)
│   │   │   ├── namuwiki.py        #   나무위키 (CC BY-NC-SA 2.0 KR)
│   │   │   ├── news.py            #   RSS + 본문
│   │   │   ├── youtube.py         #   YouTube Data API v3
│   │   │   ├── sns_scraper.py     #   Instagram·Twitter (ToS 경고)
│   │   │   └── runner.py          #   통합 CLI (collection_targets 우선·YAML 폴백)
│   │   ├── news/                  # M4: RSS 뉴스 파이프라인 (제목추출·REPORTED)
│   │   └── search/                # 외부 검색 → collection_targets 보충
│   │       ├── base.py            #   SearchProvider Protocol + SearchResult
│   │       ├── domain_grading.py  #   URL 도메인 → Grade 분류 (config/source_grading.yaml)
│   │       ├── naver.py           #   NaverSearchProvider (뉴스·블로그·웹 검색)
│   │       └── discover.py        #   CLI: search → 도메인 분류 → collection_targets upsert
│   ├── grading/                   # M3: 등급 분류 + 민감 필터
│   ├── graph/
│   │   ├── repository.py          # GraphRepository Protocol + InMemoryGraphRepository
│   │   ├── queries.py             # search·timeline·neighbors·entity_detail
│   │   ├── filters.py             # StatementFilter
│   │   ├── merge.py               # 증분 병합 (SUPERSEDED 처리)
│   │   └── entity_linker.py       # 벡터 cosine 기반 entity linking
│   ├── vault/
│   │   └── store.py               # VaultStore, VaultDoc, ConfidenceLevel
│   ├── verify/
│   │   ├── pipeline.py            # LLM cross-check (HIGH/MED/LOW)
│   │   └── graph_sync.py          # vault HIGH → 그래프 승격
│   ├── generate/
│   │   ├── llm.py                 # Ollama httpx 클라이언트
│   │   ├── qa.py                  # GraphRAG Q&A
│   │   └── reconstructive.py      # M5: 연표·요약 생성
│   ├── db/
│   │   ├── schema.sql             # PostgreSQL DDL (entities/statements/sources/vault_docs/collection_targets)
│   │   ├── connection.py          # psycopg3 연결 (DATABASE_URL)
│   │   ├── pg_repository.py       # PostgreSQLGraphRepository
│   │   ├── targets_repository.py  # CollectionTargetsRepository (수집 큐)
│   │   ├── vector_store.py        # pgvector 임베딩·유사도 검색
│   │   └── migrate.py             # JSONL + vault → PostgreSQL 마이그레이션
│   └── api/                       # M6a: FastAPI + Jinja2 + HTMX
│       ├── app.py                 # 앱 팩토리 (PostgreSQL 우선, InMemory 폴백)
│       └── routes.py              # 엔드포인트 (get_repo Generator)
├── vault/                         # raw vault (Obsidian 열기 가능)
│   ├── articles/
│   └── sns/
├── data/seed/                     # Wikidata JSONL (백업·InMemory 폴백용)
├── scripts/
│   ├── server.sh                  # start/stop/restart/status
│   └── refresh_seed.sh            # cron용 시드 갱신
└── tests/
    ├── e2e/                       # Playwright 브라우저 테스트 (53개)
    └── ...                        # 단위·통합 (243개)
```

## 7. 기술 스택 (확정)

| 레이어 | 기술 | 비고 |
|---|---|---|
| 언어 | Python 3.11+ | |
| API | FastAPI + Jinja2 + HTMX | 무빌드·서버렌더 |
| 그래프 DB | **PostgreSQL 16 + pgvector** | Docker 5433 포트; InMemory JSONL 폴백 |
| 벡터 임베딩 | **nomic-embed-text** (Ollama) | 768-dim, 엔티티 링킹·문서 검색 |
| LLM | **Ollama qwen3:14b** | Q&A·요약·검증; Anthropic API 미사용 |
| 도구 | ruff · mypy · pytest · Playwright | |
| 테스트 | 243 unit + 53 E2E | |

> 스택 변경 시 사용자에게 먼저 확인한다.

## 8. 개발 시 Claude Code 행동 지침

**이 프로젝트는 Python 백엔드다.**
- 도구: ruff(lint+format) · mypy(타입체크) · pytest(테스트)
- ⚠️ 웹/프론트엔드 훅·도구(pnpm·prettier·eslint·tsc)는 이 프로젝트에 적용하지 않는다.
- db/ 모듈은 psycopg3 stub 없음 → mypy `ignore_errors=true` 설정

**도메인 규칙:**
- 새 엔티티/관계 타입 추가 시 `docs/ontology-schema.md`와 일관되게 한다.
- 수집기 구현 시 §4-1 원칙(출처 없는 사실 없음)을 코드 레벨에서 강제한다.
- 민감 카테고리 필터는 파이프라인 입구에 두어 뒤 단계로 새지 않게 한다.
- vault 문서는 confidence=UNVERIFIED로 시작 — 생성 파이프라인에 직접 쓰지 않는다.
- GraphRepository Protocol을 통해 접근 — 구체 구현(InMemory/PostgreSQL)에 직접 의존하지 않는다.
- 법무 리스크 기능 요청은 구현 전 `docs/safety-guidelines.md` 기준으로 확인한다.

## 9. 로드맵 — 전체 완료

**완료된 마일스톤**

| 마일스톤 | 내용 | 모듈 |
|---|---|---|
| M1 | 온톨로지 타입 + validation | `ontology/` |
| M2 | Wikidata 시드 수집기 + BFS 확장 | `ingest/wikidata/` |
| M2b | 다중 루트 + 증분 병합 + SUPERSEDED | `graph/merge.py` |
| M3 | 출처 등급 분류 + 민감 필터 | `grading/` |
| M4 | RSS 뉴스 파이프라인 (공개 RSS only) | `ingest/news/` |
| M4+ | 멀티소스 수집기 (Wikipedia·나무위키·YouTube·SNS) | `ingest/collectors/` |
| M5 | 재구성형 생성 (연표·요약) | `generate/reconstructive.py` |
| M6a | 읽기전용 query API + HTMX UI | `api/` |
| M6b | GraphRAG Q&A (Ollama qwen3) | `generate/qa.py` |
| Vault | raw vault (Obsidian Markdown) | `vault/` |
| Verify | LLM cross-check 검증 파이프라인 | `verify/pipeline.py` |
| Graph Sync | vault HIGH → 그래프 승격 | `verify/graph_sync.py` |
| PostgreSQL | pgvector 저장소 + 마이그레이션 | `db/` |
| Entity Linker | 벡터 cosine 기반 링킹 | `graph/entity_linker.py` |
| E2E | Playwright 브라우저 테스트 53개 | `tests/e2e/` |
| Scheduling | cron/launchd 주기 갱신 | `scripts/refresh_seed.sh` |
| Search Discovery | 외부 검색 → 도메인 등급 → 수집 큐 보충 | `ingest/search/` + `config/source_grading.yaml` |

⚠️ **M4 추가 확장 전 선행 확인**: 공개 RSS 외 추가 피드 사용 시 ToS·라이선스 검토 필수.
⚠️ **나무위키 CSR 한계**: headless browser 없이 본문 불가 — TOC 구조만 수집됨.
⚠️ **Naver Search API**: NAVER_CLIENT_ID·NAVER_CLIENT_SECRET 환경변수 필요. 미설정 시 graceful 빈 결과.
