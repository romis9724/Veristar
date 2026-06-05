# Veristar — 서비스 설계

> 2026-06-04 deep-interview로 확정한 서비스 방향. `CLAUDE.md`(상위 규칙) > 이 문서 순으로 우선한다.

---

## 1. 한 줄 정의

한국 연예인 지식그래프 위에서 **구조적 그래프 탐색(검색)** 을 메인으로,  
**재구성형 콘텐츠 생성**과 **GraphRAG 자연어 Q&A**를 보조로 얹은 서비스.

## 2. 핵심 결정 요약

| 항목 | 결정 | 근거 |
|---|---|---|
| 수집 대상 | **한국 연예인 전반** (가수·배우·유튜버·코미디언) | 2026-06-04 인터뷰 |
| 저장 구조 | **3-레이어** (raw vault + knowledge graph + service) | 수집 우선·검증 후행 |
| 검색 방식 | 구조적 그래프 탐색 + 벡터 의미 검색 | 온톨로지·pgvector 강점 |
| 생성 방식 | 재구성형만 (추론형 금지) | CLAUDE.md §4 |
| 민감 정보 | raw 수집 허용 → 생성·API에서 차단 | 2026-06-04 인터뷰 |
| 스택 | Python 3.11 / FastAPI / PostgreSQL+pgvector / Ollama | §7 |

## 3. 아키텍처 — Karpathy "LLM Wiki" 3-레이어

```
[Layer 1] raw vault (Obsidian Markdown)
    ─ 수집기들이 원본 콘텐츠를 vault/*.md에 저장
    ─ frontmatter: id·source_type·confidence·license·sensitive
    ─ LLM cross-check → confidence: unverified → high/medium/low

[Layer 2] knowledge graph (PostgreSQL + pgvector)
    ─ entities, statements, sources, vault_docs 테이블
    ─ vector(768): nomic-embed-text로 엔티티·문서 임베딩
    ─ Wikidata OFFICIAL backbone + vault HIGH 승격분
    ─ GraphRepository Protocol → InMemory(파일) 또는 PostgreSQL

[Layer 3] service (FastAPI / Jinja2 / HTMX)
    ─ GET /api/entities, /statements, /timeline, /neighbors
    ─ GET /api/qa (GraphRAG, Ollama qwen3)
    ─ GET /ui/* (HTMX 탐색 UI, 타입어헤드, 필터)
    ─ OFFICIAL + sensitive=false만 콘텐츠 재료
```

| Karpathy LLM Wiki | Veristar 대응 |
|---|---|
| ① 원문 소스 (불변) | raw vault + Source 레코드 |
| ② wiki = 지식층 | reified-statement 그래프 (출처+등급 필수) |
| ③ 스키마 = config | `CLAUDE.md` |
| `ingest` | 수집기 → vault → 그래프 승격 |
| `query` | 그래프 탐색 API + 벡터 검색 |
| `lint` | validation + status 전이 + 민감 필터 |

## 4. 데이터 수집

### 4.1 [1] Wikidata 시드 — 자동, 완전 구현

- **입력**: `config/roots.txt` QID 목록 (10개: K-pop 그룹 6 + 소속사 4 + G-Dragon)
- **수집**: BFS로 관련 엔티티 확장. 레퍼런스 달린 claim만 OFFICIAL.
- **매핑**: P463→memberOf, P800→appearedIn, P166→wonAward, P1411→nominatedFor
- **갱신**: 24h 자동 갱신 (`VERISTAR_REFRESH_INTERVAL_HOURS`)

### 4.1b 수집 대상 자동 발견 (SPARQL) — 구현 완료

수동 목록(celebrities.yaml) 대신 Wikidata SPARQL로 한국 연예인을 대량 발견한다.

```
ingest/wikidata/sparql.py (WDQS 직업별 쿼리)
    P27=Q884(한국) + P106(직업) + kowiki sitelink
    직업: singer(가수·아이돌)·actor(배우)·entertainer(예능)·creator(유튜버)·group(그룹)
    ↓
ingest/wikidata/discover.py (CLI)
    ↓
PostgreSQL collection_targets (status=pending)
```

- **규모**: kowiki sitelink 필터(유명 인물)로 직업당 수천 명. 상한 없음.
- **상태 추적**: status(pending/collecting/done/failed)·priority·last_collected_at.
- **roots.txt와 독립**: collection_targets는 멀티소스 수집 큐, roots.txt는 Wikidata BFS 그래프 시드.
- **WDQS rate-limit**: 429 지수 백오프(Retry-After 존중), 직업 그룹별 쿼리 분할.

### 4.2 [2] 멀티소스 수집기 — 구현 완료

```
PostgreSQL collection_targets (우선) 또는 celebrities.yaml (폴백)
    ↓
ingest/collectors/runner.py (통합 CLI) — pending 대상 로드, 완료 시 done 마킹
    ├── wikipedia.py   → vault/articles/ (CC BY-SA 4.0)
    ├── namuwiki.py    → vault/articles/ (CC BY-NC-SA 2.0 KR) ⚠️ CSR 한계
    ├── news.py        → vault/articles/ (RSS + 본문, 언론사 저작권)
    ├── youtube.py     → vault/sns/ (YouTube Data API v3)
    └── sns_scraper.py → vault/sns/ (ToS 위험 명시)
```

**나무위키 한계**: 완전 CSR — headless browser 없이 본문 불가. 현재는 TOC 구조·메타만 수집.

### 4.3 [3] LLM 검증 파이프라인 — 구현 완료

```
vault (UNVERIFIED)
    ↓ verify/pipeline.py (Ollama qwen3)
    ├── HIGH   → 자동 승인 → verify/graph_sync.py → PostgreSQL
    ├── MEDIUM → 큐 대기 (사람 검토)
    └── LOW    → 폐기
```

### 4.4 [4] 뉴스 RSS 파이프라인 (M4) — 구현 완료

```
config/news_feeds.yaml (공개 RSS만)
    → ingest/news/rss.py (제목·URL·날짜 추출, 본문 복제 없음)
    → ingest/news/extractor.py (LLM 사실 추출, 엔티티 링킹)
    → REPORTED 등급 statements
```

⚠️ 추가 피드 사용 전 ToS·라이선스 반드시 검토.

### 4.5 [5] 외부 검색 발견 파이프라인 — 구현 완료

URL을 직접 알지 못해도 쿼리로 발견한 뒤 등급 분류 후 수집 큐에 추가한다.

```
NaverSearchProvider.search(query)    # 뉴스·블로그·웹 통합 검색
    ↓
DomainGrading.classify(url)          # config/source_grading.yaml 도메인 화이트리스트
    ├── OFFICIAL  → collection_targets upsert (즉시 크롤링 대상)
    ├── REPORTED  → collection_targets upsert
    ├── RUMOR     → --include-rumor 옵션 없으면 건너뜀
    └── blocked   → 항상 차단
    ↓
다음 cron: collectors.runner → vault → verify/pipeline → HIGH 시 그래프 승격
```

**설정**:
- `config/source_grading.yaml`: official/reported/blocked 도메인 화이트리스트
- 환경변수: `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` (미설정 시 graceful 빈 결과)

**CLI 사용법**:
```bash
python -m veristar.ingest.search.discover --query "스트레이 키즈 신곡"
python -m veristar.ingest.search.discover --query "블랙핑크" --limit 20 --include-rumor
```

## 5. 검색(query) 설계

### 5.1 구조적 그래프 탐색 (메인)

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/entities?q=` | 이름·alias 텍스트 검색 (ILIKE + 벡터 폴백) |
| `GET /api/entities/{id}` | 엔티티 상세 (outgoing/incoming count) |
| `GET /api/entities/{id}/statements` | 연결된 statements (grade/predicate/status/date 필터) |
| `GET /api/entities/{id}/timeline` | valid_from 시간순 정렬 |
| `GET /api/entities/{id}/neighbors` | 그래프에 실재하는 인접 엔티티 |
| `GET /api/entities/{id}/summary` | LLM 재구성형 요약 (OFFICIAL만, 추론 없음) |
| `GET /api/health` | 상태 + 저장소 종류 + 통계 |

### 5.2 벡터 의미 검색 (pgvector)

| 기능 | 메서드 | 설명 |
|---|---|---|
| 유사 엔티티 | `VectorStore.find_similar_entities()` | cosine similarity (threshold 0.82) |
| 문서 검색 | `VectorStore.search_vault_docs()` | RAG 컨텍스트 수집 |
| 중복 감지 | `VectorStore.find_duplicate_vault_docs()` | similarity ≥ 0.96 |

### 5.3 자연어 Q&A — GraphRAG (M6b)

```
GET /api/qa?q=질문
    → 엔티티 탐색 (find_mentioned with vectors)
    → OFFICIAL statements 수집
    → Ollama qwen3 컨텍스트 grounding
    → 답변 (그래프 근거 외 추론 없음)
```

## 6. 엔티티 링킹

**문제**: 짧은 이름('한', '뷔') substring 매칭 → cross-group false-positive  
**해결**: `graph/entity_linker.py` — 3자 이하 이름은 cosine 검증 필수

```python
# 길이 > 3자: substring 매칭만으로 통과
# 길이 ≤ 3자: embed_text() → cosine ≥ 0.82 필요
find_mentioned_with_vectors(text, repo, limit=5, threshold=0.82)
```

PostgreSQL 모드에서는 `VectorStore.find_similar_entities()`로 DB 레벨 벡터 검색.

## 7. 기술 스택

| 레이어 | 기술 | 세부 |
|---|---|---|
| 언어 | Python 3.11+ | |
| API | FastAPI 0.110+ | GraphRepository Protocol 기반 |
| UI | Jinja2 + HTMX | 무빌드·타입어헤드·필터 |
| 그래프 DB | **PostgreSQL 16 + pgvector** | Docker 5433; InMemory JSONL 폴백 |
| 벡터 | **nomic-embed-text** (Ollama) | 768-dim · 한영 다언어 |
| LLM | **Ollama qwen3:14b** | Q&A·요약·검증; Anthropic API 미사용 |
| 도구 | ruff · mypy(strict) · pytest | |
| E2E | Playwright Chromium | 53개 테스트 |
| 저장 폴백 | JSONL + Markdown vault | PostgreSQL 없을 때 자동 전환 |

### 저장소 전환 전략

```python
# api/app.py — 자동 감지
if is_available():   # PostgreSQL 연결 가능
    use_postgres = True   # → PostgreSQLGraphRepository (요청마다 커넥션)
else:
    use_postgres = False  # → InMemoryGraphRepository.from_path(seed.json)
```

## 8. 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `postgresql://veristar:veristar@localhost:5433/veristar` | PostgreSQL DSN |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama 주소 |
| `VERISTAR_LLM_MODEL` | `qwen3:14b` | LLM 모델 |
| `VERISTAR_EMBED_MODEL` | `nomic-embed-text` | 임베딩 모델 |
| `VERISTAR_LINK_THRESHOLD` | `0.82` | 엔티티 링킹 cosine 임계값 |
| `VERISTAR_SEED_PATH` | `data/seed/wikidata_seed.json` | JSONL 시드 경로 |
| `VERISTAR_REFRESH_INTERVAL_HOURS` | `24` | 시드 자동 갱신 주기 |
| `VERISTAR_ROOTS_FILE` | `config/roots.txt` | Wikidata 루트 QID 파일 |
| `VERISTAR_MAX` | `80` | BFS 최대 엔티티 수 |

## 9. 현재 데이터 현황 (2026-06-04)

| 항목 | 수량 |
|---|---|
| 엔티티 | 78개 (K-pop 그룹·멤버·소속사) |
| Statements | 130개 (OFFICIAL 114 + REPORTED 16) |
| Sources | 77개 |
| vault_docs | 87건 (Wikipedia 20 + 나무위키 7 + 뉴스 60) |
| Wikidata 루트 | 10개 (그룹 6 + 소속사 4 + G-Dragon) |
| collection_targets | SPARQL 발견 (group 1966건 적재, 직업 확장 시 수천 명) |

## 10. 열린 과제

1. **나무위키 본문 수집**: headless browser(Playwright) 도입 필요.
2. **M4 추가 피드**: ToS·라이선스 확인 후 추가 가능.
3. **MEDIUM 큐 처리**: 사람 검토 UI 미구현.
4. **벡터 인덱스 최적화**: IVFFlat (엔티티 수 100+ 시 활성화).
5. **수집 대상 확장**: `discover.py`로 SPARQL 재실행 (직업 추가·필터 조정).
