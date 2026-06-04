# Veristar

> 출처 등급으로 검증한 연예 지식그래프(Knowledge Graph)와, 그 위에서 안전하게 동작하는 콘텐츠 생성 시스템.
> 이름은 *veritas*(진실) + *star*(스타)에서 왔다.

이 문서는 Claude Code가 이 프로젝트를 다룰 때 따라야 할 **상위 규칙**이다.
세부 데이터 모델은 `docs/ontology-schema.md`, 안전 규칙은 `docs/safety-guidelines.md`,
서비스(검색+생성) 설계는 `docs/service-design.md`를 본다.

---

## 1. 한 줄 정의

연예 도메인의 엔티티(인물·그룹·소속사·작품·이벤트)와 관계를 그래프로 구조화하되,
**모든 사실(assertion)에 출처와 신뢰 등급을 붙이고**, 그중 "공식 확인된" 사실만 콘텐츠 생성의 재료로 쓴다.

## 2. 무엇이 이 프로젝트의 차별점인가

연예 정보 DB는 이미 많다(나무위키, IMDb, MusicBrainz, kprofiles 등).
Veristar의 유일한 차별점은 **출처 검증(provenance)** 이다. 따라서:

- 모든 노드/엣지는 "누가, 언제, 어디서 말했는가"를 데이터로 가진다.
- 시스템은 "이게 **진실인가**"를 판정하지 않는다 (불가능하고 위험하다).
- 대신 "이게 **공식 출처에서 나왔는가**"라는, 객관적으로 판정 가능한 것만 판정한다.

이 원칙을 깨는 설계 변경은 프로젝트의 정체성을 무너뜨리는 것이므로, 제안 전 반드시 사용자에게 확인한다.

## 3. 데이터 파이프라인 (2-레이어 아키텍처, 2026-06-04 정책 전환)

```
[Layer 1] raw vault (Obsidian Markdown)
    수집기 → Wikipedia·나무위키·뉴스·YouTube·SNS → vault/*.md
        ↓ LLM cross-check (verify pipeline)
[Layer 2] knowledge graph (JSONL, 기존)
    confidence=HIGH → JSONL 그래프 승격 (Wikidata backbone 교차확인)
        ↓ query API
[Layer 3] service (FastAPI / HTMX)
    OFFICIAL 등급만 콘텐츠 재료로 사용
```

**정책 변경 (2026-06-04 인터뷰 결정)**:
- 수집 대상: 한국 연예인 전반 (가수·배우·유튜버·코미디언)
- 민감 정보: **raw 수집 허용** (sensitive=true 플래그) → 생성·API 노출 단계에서만 차단
- 검증 방식: LLM cross-check → HIGH 자동승인·MEDIUM 큐·LOW 폐기
- 나무위키: CC BY-NC-SA 2.0 KR 라벨 필수, 비상업적 사용 조건 준수
- SNS 스크래핑: ToS 위반 위험 인지 상태로 수집 (sns_scraper.py 경고 명시)

## 4. 절대 원칙 (Non-negotiable)

코드를 짤 때 아래는 기능이 아니라 **제약**이다. 어기는 코드는 작성하지 않는다.

1. **출처 없는 사실은 없다.** 모든 statement는 최소 1개의 source 참조가 필수다. source 없는 노드/엣지는 적재 거부.
2. **등급은 출처의 성격이지 진실 여부가 아니다.** `OFFICIAL`은 "공식 발표됨"을 뜻하지 "사실로 입증됨"을 뜻하지 않는다.
3. **콘텐츠 재료는 `OFFICIAL`만.** `REPORTED`/`RUMOR`는 그래프에는 저장하되, 생성 입력으로는 절대 넣지 않는다.
4. **생성은 재구성(reconstructive)만.** 입력에 없던 관계·평가·예측을 새로 만들어내는 추론형(inferential) 생성은 기본적으로 금지. (자세한 정의는 §5)
5. **민감 정보: raw vault에는 저장 가능, API·생성에서 차단.** `sensitive=true` 플래그로 표시. 콘텐츠 생성·공개 API 응답에서 필터링 필수.
6. **나무위키 콘텐츠는 CC BY-NC-SA 라벨 필수.** 상업화 전 별도 검토.

## 5. 콘텐츠 생성: 허용 / 금지

| 유형 | 정의 | 허용? |
|---|---|---|
| 재구성형 (Reconstructive) | OFFICIAL 사실의 요약·정리·연표화·번역. **새 정보 추가 없음** | ✅ |
| 추론형 (Inferential) | 관계 추측, 미래 예측, 평가·해석 추가 | ❌ (기본 금지) |

판단 기준: **출력에 입력 statement에 없던 사실이 새로 생겼는가?** 생겼다면 거짓을 만들었을 위험이 있으므로 차단.

## 6. 디렉토리 구조

```
veristar/
├── CLAUDE.md                  # (이 파일) 상위 규칙
├── README.md
├── docs/
│   ├── ontology-schema.md     # 엔티티·관계·출처 모델 정의
│   ├── safety-guidelines.md   # 법무·윤리 가드레일
│   └── service-design.md      # 검색+보조생성 서비스 설계 (아키텍처·데이터·1차 범위)
├── pyproject.toml             # 패키지·의존성·ruff/mypy/pytest 설정
├── src/veristar/              # 최상위 패키지 (veristar.README.md = 모듈 맵)
│   ├── ontology/              # ✅ M1: 데이터 모델(타입) + validation (스키마 §5)
│   ├── ingest/                # [1][2] wiki / news 수집기
│   ├── grading/               # [3] 출처 등급 분류 로직
│   ├── graph/                 # [4] 그래프 저장소 인터페이스
│   └── generate/              # [5] 콘텐츠 생성 (재구성형만)
├── data/
│   ├── seed/                  # wiki 기반 시드 데이터
│   └── examples/              # 스키마 예시(sample.json)
└── tests/
```

## 7. 기술 스택 (확정 — 2026-06-04)

> 1차 스택은 인터뷰로 확정됨(`docs/service-design.md` §7). 바꿀 때는 사용자에게 먼저 묻는다.

- 언어: **Python 3.11+**
- query API: **FastAPI** (1차 = 읽기전용 엔드포인트)
- 그래프 저장: **파일 기반 JSONL** → 규모 커지면 Neo4j 또는 RDF 트리플스토어 검토(Repository 패턴으로 교체 가능하게)
- 도구: ruff(lint/format) · mypy(타입) · pytest(테스트) — §8 참조
- LLM(요약·Q&A): **로컬 Ollama qwen3** (앤트로픽 API 미사용). 설정: `OLLAMA_HOST`(기본 localhost:11434)·`VERISTAR_LLM_MODEL`(기본 `qwen3:14b`). 클라이언트 `src/veristar/generate/llm.py`
- 시드 소스: Wikidata(CC0, 라이선스 자유 — 적극 활용), Wikipedia
- 뉴스: **스크래핑 대신 공개 API/RSS 우선.** 네이버·다음 본문 크롤링은 약관·저작권 문제 → 지양
- 최소 탐색 UI 프론트: **FastAPI + Jinja2 + HTMX** (확정 2026-06-04 — 무빌드·Python 단일 스택)

## 8. 개발 시 Claude Code 행동 지침

**이 프로젝트는 Python 백엔드다.** (UI는 1차 후행, 미정)
- 도구: **ruff**(lint+format) · **mypy**(타입체크) · **pytest**(테스트). 리뷰는 `python-reviewer`, 패턴은 `python-patterns`, 테스트는 `python-testing` 스킬/에이전트를 쓴다.
- ⚠️ 전역 규칙에 깔린 **웹/프론트엔드 훅·도구(pnpm·prettier·eslint·tsc)는 이 프로젝트에 적용하지 않는다.** 그건 web 스택용이다. (최소 탐색 UI를 Next.js로 갈 경우에만 부분 적용)

**도메인 규칙:**
- 새 엔티티/관계 타입을 추가할 때는 먼저 `docs/ontology-schema.md`를 읽고, 거기 정의와 일관되게 한다.
- 수집기를 만들 때 §4의 "출처 없는 사실은 없다"를 코드 레벨에서 강제한다(스키마 validation).
- 민감 카테고리 필터는 파이프라인 입구에 두어 그 뒤 단계로 새지 않게 한다.
- 법무 리스크가 보이는 기능 요청을 받으면, 구현 전에 `docs/safety-guidelines.md` 기준으로 짚고 사용자에게 확인한다.

## 9. 로드맵

서비스 방향 확정(2026-06-04, `docs/service-design.md`)에 따라 **데이터 우선 + 검색 1차 출시**로 재배치한다.

**완료 — 로드맵 전 마일스톤 구현됨**
- ✅ **M1** 온톨로지 데이터 모델(타입) + validation (스키마 §5)
- ✅ **M2** Wikidata 시드 수집기(루트 QID 확장, 레퍼런스 달린 OFFICIAL만) → `src/veristar/ingest/wikidata`.
- ✅ **M2b** 다중 루트 scope(`config/roots.txt`) + 증분 병합·SUPERSEDED 저장소
- ✅ **M3** 출처 등급 분류기 + 민감 카테고리 필터 → `src/veristar/grading`
- ✅ **M5** 재구성형 콘텐츠 생성기(연표·요약) → `src/veristar/generate/reconstructive.py`
- ✅ **M6a** 읽기전용 query API + HTMX 탐색 UI(등급·관계 필터, 요약 버튼)
- ✅ **M6b** 자연어 Q&A(GraphRAG, 로컬 Ollama qwen3 grounding) → `src/veristar/generate/qa.py`·`generate/llm.py`
- ✅ **Scheduling** `scripts/refresh_seed.sh` (cron/launchd 주기적 갱신)

- ✅ **M4** 뉴스 RSS 파이프라인(공개 RSS only) → `src/veristar/ingest/news/` — 제목추출·REPORTED등급·민감필터
- ✅ **Wikipedia 별칭** `src/veristar/ingest/wikipedia/alias_supplement.py` — kowiki redirect → alias 보완

⚠️ **M4 추가 확장 전 선행 확인**: 공개 RSS 외 추가 피드 사용 시 해당 서비스 ToS·라이선스 반드시 검토.

> 검색 서비스 = Karpathy "LLM Wiki" 패턴의 `query` 연산. 단 지식층은 자유 마크다운이 아니라 **출처 검증 그래프**다. (`docs/service-design.md` §3)
