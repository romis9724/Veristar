# Veristar

> *veritas*(진실) + *star*(스타) — 출처 등급으로 검증한 한국 연예인 지식그래프와 안전한 콘텐츠 생성 시스템.

모든 사실에 **출처와 신뢰 등급**을 붙이고, "공식 확인된" 사실만 콘텐츠 재료로 쓴다.  
시스템은 "이게 진실인가"를 판정하지 않는다 — "이게 **공식 출처에서 나왔는가**"만 판정한다.

## 아키텍처 (3-레이어)

```
[Layer 1] raw vault (Obsidian Markdown)
    수집기 → Wikipedia·나무위키·뉴스·YouTube·SNS → vault/*.md
              ↓ LLM cross-check (confidence 분류)
[Layer 2] knowledge graph (PostgreSQL + pgvector)
    HIGH confidence → 그래프 승격 · Wikidata backbone 교차 확인
              ↓ GraphRepository Protocol
[Layer 3] service (FastAPI / HTMX)
    OFFICIAL 등급만 콘텐츠 재료 · 민감 정보 API 레벨 차단
```

## 신뢰 등급

| 등급 | 의미 | 콘텐츠 재료 |
|---|---|---|
| `OFFICIAL` | 공식 발표·Wikidata 검증 | ✅ |
| `REPORTED` | 언론 보도, 공식 미확인 | ❌ |
| `RUMOR` | 미검증 | ❌ |

## 문서

| 파일 | 내용 |
|---|---|
| [`CLAUDE.md`](./CLAUDE.md) | Claude Code 상위 규칙 |
| [`docs/ontology-schema.md`](./docs/ontology-schema.md) | 엔티티·관계·출처·vault 모델 |
| [`docs/safety-guidelines.md`](./docs/safety-guidelines.md) | 법무·윤리 가드레일 |
| [`docs/service-design.md`](./docs/service-design.md) | 전체 서비스 설계 |

## 디렉토리 구조

```
veristar/
├── docker-compose.yml         # PostgreSQL 16 + pgvector
├── config/
│   ├── roots.txt              # Wikidata 루트 QID (10개 그룹·소속사)
│   └── news_feeds.yaml        # RSS 피드 설정
│                              # (수집 대상은 PostgreSQL collection_targets — SPARQL 자동 발견)
├── vault/                     # raw vault (Obsidian 호환 Markdown)
│   ├── articles/              # Wikipedia·나무위키·뉴스 기사
│   └── sns/                   # YouTube·SNS 메타데이터
├── src/veristar/
│   ├── ontology/              # M1: 데이터 모델 + validation
│   ├── ingest/
│   │   ├── wikidata/          # M2: Wikidata 시드 수집기
│   │   ├── wikipedia/         # Wikipedia 별칭 보완
│   │   ├── collectors/        # 멀티소스 수집기 (Wikipedia·Namu·News·YouTube·SNS)
│   │   └── news/              # M4: RSS 뉴스 파이프라인
│   ├── grading/               # M3: 출처 등급 분류 + 민감 필터
│   ├── graph/                 # 저장소 Protocol + InMemory 구현 + entity linker
│   ├── vault/                 # raw vault 저장소 (VaultStore, VaultDoc)
│   ├── verify/                # LLM 검증 파이프라인 + 그래프 승격
│   ├── generate/              # M5: 재구성형 생성 / M6b: GraphRAG Q&A
│   ├── db/                    # PostgreSQL + pgvector (schema, migration, repository)
│   └── api/                   # M6a: FastAPI + Jinja2 + HTMX
├── data/seed/                 # Wikidata JSONL 시드 (백업)
└── tests/
    ├── e2e/                   # Playwright 브라우저 테스트 (53개)
    └── ...                    # 단위·통합 테스트 (184개)
```

## 빠른 시작

### 필수 조건

```bash
# Python 가상환경
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# Ollama (LLM + 임베딩)
ollama pull qwen3:14b        # Q&A·요약·검증
ollama pull nomic-embed-text  # 벡터 임베딩 (entity linking)
```

### 1. PostgreSQL 시작

```bash
docker compose up -d          # postgres:16 + pgvector (포트 5433)
```

### 2. 시드 수집 → DB 적재

```bash
# Wikidata 시드 수집 (10개 루트)
python -m veristar.ingest.wikidata.seed \
  --roots-file config/roots.txt --max 80 --allow-unreferenced

# JSONL + vault → PostgreSQL 마이그레이션 + 임베딩 생성
python -m veristar.db.migrate \
  --seed data/seed/wikidata_seed.json \
  --vault vault/ \
  --embed
```

### 3. 수집 대상 자동 발견 (SPARQL)

```bash
# Wikidata SPARQL로 한국 연예인 대량 발견 → collection_targets 적재
# 직업: singer(가수·아이돌) actor(배우) entertainer(예능) creator(유튜버) group(그룹)
python -m veristar.ingest.wikidata.discover \
  --occupations singer,actor,entertainer,creator,group
#  → kowiki sitelink 있는 유명 인물만 (수천 명 규모)
```

### 4. 추가 콘텐츠 수집 (선택)

```bash
# 멀티소스 수집 — collection_targets에서 pending 대상을 읽어 수집
# (DB 연결 불가 시 config/celebrities.yaml 폴백)
python -m veristar.ingest.collectors.runner \
  --vault vault/ --sources wikipedia,namuwiki,news \
  --limit 100   # pending 중 100건만 (생략 시 전체)

# LLM 검증 (unverified → HIGH/MEDIUM/LOW)
python -m veristar.verify.pipeline --vault vault/

# HIGH docs → 그래프 승격
python -m veristar.verify.graph_sync \
  --vault vault/ --seed data/seed/wikidata_seed.json
```

### 5. 서버 시작

```bash
./scripts/server.sh start
# → http://localhost:8000  (PostgreSQL 자동 감지)
```

## 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `postgresql://veristar:veristar@localhost:5433/veristar` | PostgreSQL DSN |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama 서버 주소 |
| `VERISTAR_LLM_MODEL` | `qwen3:14b` | Q&A·요약·검증 모델 |
| `VERISTAR_EMBED_MODEL` | `nomic-embed-text` | 벡터 임베딩 모델 |
| `VERISTAR_LINK_THRESHOLD` | `0.82` | 엔티티 링킹 cosine 임계값 |
| `VERISTAR_REFRESH_INTERVAL_HOURS` | `24` | 시드 자동 갱신 주기 (0=비활성) |

## 품질 게이트

```bash
ruff check . && ruff format --check . && mypy src && pytest
# → 184 unit tests + 53 E2E tests (Playwright Chromium)
```

## 현재 상태 (2026-06-04)

🟢 **전체 구현 완료**

| 지표 | 값 |
|---|---|
| 엔티티 | 78개 (K-pop 그룹·멤버·소속사) |
| Statements | 130개 (OFFICIAL + REPORTED) |
| Raw vault | 87건 (Wikipedia 20 + 나무위키 7 + 뉴스 60) |
| 단위 테스트 | 184개 · 83% 커버리지 |
| E2E 테스트 | 53개 · Playwright Chromium |
| 저장소 | PostgreSQL 16 + pgvector |
