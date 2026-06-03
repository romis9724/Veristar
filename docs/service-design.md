# Veristar — 서비스 설계 (지식 검색 + 보조 콘텐츠 생성)

> 2026-06-04 deep-interview로 확정한 서비스 방향. 이 문서는 `CLAUDE.md`(상위 규칙)·`docs/ontology-schema.md`(데이터 모델)·`docs/safety-guidelines.md`(가드레일) 아래에 위치한다. 충돌 시 `CLAUDE.md`의 절대 원칙이 우선한다.

---

## 1. 한 줄 정의

Veristar 지식그래프 위에서 **구조적 그래프 탐색(검색)** 을 메인으로 하고, 검색 결과를 정리하는 **재구성형 콘텐츠 생성**을 보조로 얹은 서비스.

## 2. 핵심 결정 요약

| 항목 | 결정 | 근거 |
|---|---|---|
| 성격 | 검색이 메인, 생성은 보조 | "확장형"을 형식·탐색의 확장으로 해석 → §5 재구성형 원칙 유지 |
| 검색 방식 | **구조적 그래프 탐색** 1순위 | 온톨로지 강점(엔티티·관계·출처등급)이 그대로 드러남, LLM 불필요 |
| 확장 대비 | 레이어드 (UI ↔ query API ↔ 저장소) | 향후 자연어 Q&A·키워드상세·API-only 수용 |
| 아키텍처 골격 | Karpathy "LLM Wiki" **구조만 채택** | §3 참조 |
| 데이터 시작 | M1→M2 먼저, 실데이터 위에 검색 | 데이터가 기반 기술 |
| 1차 완성 | query API + 최소 탐색 UI (읽기전용) | §7 |
| 스택 | Python 3.11+ / FastAPI / JSONL | `CLAUDE.md` §7 제안과 일치 |

## 3. 아키텍처 — Karpathy "LLM Wiki" 구조 채택

[Karpathy의 LLM Wiki 패턴](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)(원문에서 매번 RAG 하지 말고, LLM이 누적되는 지식층을 증분 유지)에서 **구조만** 가져온다. 3계층·3연산을 서비스 골격으로 쓰되, **wiki층을 "자유 마크다운"이 아니라 "출처 검증된 그래프"로 대체**한다 — 이것이 Veristar의 정체성이다.

```
①  원문 소스 (불변)          ②  지식층                    ③  스키마/규칙
   Wikidata·뉴스 링크    →    reified-statement 그래프  ←   CLAUDE.md
   (본문 복제 X)              (출처+등급 필수, 검증됨)        (이 규칙)
```

| Karpathy LLM Wiki | Veristar 대응 | 비고 |
|---|---|---|
| ① 원문 소스(불변) | Source 레코드 + 원문은 링크만 | 저작권 §3 |
| ② wiki = LLM 자유 마크다운 | **reified-statement 그래프** | ⚠️ 자유 마크다운 금지. 마크다운은 OFFICIAL에서 재구성 렌더링만 |
| ③ 스키마 = config | `CLAUDE.md` | 이미 존재 |
| `ingest` 연산 | 파이프라인 [1][2] (`src/ingest`) | 소스 처리·엔티티 링크·교차참조 |
| `query` 연산 | **검색 서비스** (`src/graph` 조회 + API) | 본 문서의 메인 |
| `lint` 연산 | validation(§5) + status 전이 + 민감필터 감사 | 모순·낡은 주장·고아 점검 |

> 참고 구현: 이 저장소 환경의 `brain-workflow` 스킬(clip/ingest/lint)이 동일 패턴의 운영 레퍼런스다.

## 4. 데이터 수집 (기반 기술)

> 가치와 위험이 모두 수집에 몰려 있다. 무인 스크래퍼는 `docs/safety-guidelines.md` 위반이므로 만들지 않는다.

### 4.1 [1] Wikidata 시드 — 근시일 구현, 완전 자동

1. **Wikidata Query Service(SPARQL)** 로 도메인 한정 크롤 → QID 목록.
2. P-속성을 Veristar predicate로 **결정론적 매핑**(LLM 없음):

   | Wikidata | Veristar predicate |
   |---|---|
   | P527(has part)/P463(member of) | `memberOf` |
   | P175(performer)/P800(notable work) | `appearedIn`/`released` |
   | P166(award received) | `wonAward` |
   | P1411(nominated for) | `nominatedFor` |
   | P580(start time) 한정자 | `valid_from` |

3. **QID를 그대로 `id`(`wd:Q...`)** 로. 출처 = Wikidata 엔티티 URL, `source_type=WIKIDATA_VERIFIED` → `OFFICIAL`.
4. **정제 규칙**: 무조건 OFFICIAL 부여하지 말고, **레퍼런스(P-statement reference)가 달린 claim만** OFFICIAL로 받는다.

- 성격: 라이선스(CC0)·환각 위험 0의 **정적 백본**. 검색 1차는 이 위에 올린다.
- 한계: 신인·최신 발매·최근 수상 커버리지는 얇음 → 신선도는 [2]가 책임(후행).

### 4.2 [2] 뉴스 수집 — 설계만, 구현은 후행

자동화 수준 결정: **시드만 먼저** — 1차엔 [1]만 자동화하고 [2]는 설계만 둔다.

```
fetch(링크/제목만)
  → extract(제약된 LLM: 원문에 문자 그대로 있는 것만, source URL 필수)
  → entity-link(이름 → 기존 QID, 동명이인 disambiguation)
  → 민감 필터 (입구 차단)            ← 가장 중요한 게이트
  → grade(REPORTED 기본)
  → validate(스키마 §5)
  → 멱등 upsert(SUPERSEDED/RETRACTED 상태 처리)
```

- **소스 범위**: 소속사 공식 보도자료/공식 채널(→`OFFICIAL_ANNOUNCEMENT`→OFFICIAL, 콘텐츠 재료 가능) + 허용된 RSS·공개 뉴스 API(→REPORTED). 링크·제목만 보관, 본문 복제 금지. 네이버·다음 본문 크롤링 지양.
- **민감·경계·등급승격 후보는 사람 검수 큐**로(자동 적재 금지).
- 다수 매체 교차 보도여도 OFFICIAL 승격 안 함 — **공식 출처가 붙을 때만**.
- 구현 전 선행 과제: 사용할 뉴스 소스의 ToS·라이선스 검증.

## 5. 검색(query) 설계 — 1차 메인

읽기 전용. 입력 데이터는 `src/graph` 저장소.

- **엔티티 검색**: 이름·alias 키워드 → 후보 엔티티 목록.
- **관계 탐색**: 엔티티 선택 → 연결된 statement(predicate·object·출처·등급·valid_from/to) 펼치기.
- **연표 뷰**: statement를 `valid_from` 기준 시간순 정렬.
- **필터**: `grade`(OFFICIAL/REPORTED/RUMOR), 기간, predicate 타입, `status`(기본 ACTIVE만).
- **출처 노출**: 모든 표시 항목은 Source(=출처 등급·URL)를 함께 보여준다. 이게 Veristar의 차별점.

확장 슬롯(후행): 자연어 Q&A(GraphRAG)는 같은 query API 위에 레이어로 추가.

## 6. 콘텐츠 생성(보조) — 1차 미포함

- 입력 게이트: `grade==OFFICIAL AND sensitive==false AND status==ACTIVE` 쿼리 결과만.
- 허용: 연표·요약·번역 등 **재구성**. 금지: 추론형(관계 추측·평가·예측) — `CLAUDE.md` §5.
- 판단 기준: 출력에 입력 statement에 없던 사실이 생기면 차단.

## 7. 기술 스택

| 레이어 | 선택 | 비고 |
|---|---|---|
| 언어 | Python 3.11+ | `CLAUDE.md` §7 |
| query API | FastAPI | 읽기전용 엔드포인트 |
| 그래프 저장 | 파일 기반 JSONL | 규모 확대 시 Neo4j/RDF 검토(Repository 패턴으로 교체 가능하게) |
| 최소 탐색 UI | **미정 (열린 질문)** | 추천: FastAPI+Jinja2+HTMX(KISS·무빌드) vs Next.js |

## 8. 1차 완성 범위 & 완료 기준

**범위**: 소규모 Wikidata 시드 그래프 위의 읽기전용 query API + 최소 탐색 UI. 생성·뉴스 미포함.

**완료 기준 (Definition of Done)**
- [ ] M1: ontology 타입 + 스키마 §5의 6개 validation 규칙 구현, 테스트 통과.
- [ ] M2: Wikidata SPARQL 시드 수집기 — 인물·그룹 등 수십 개 엔티티를 JSONL 그래프로 적재(레퍼런스 달린 OFFICIAL만).
- [ ] query API: 엔티티 검색 / 관계·연표 조회 / 등급·기간 필터 엔드포인트.
- [ ] 최소 탐색 UI: 검색 → 엔티티 → 관계·연표·**출처등급** 탐색.
- [ ] 모든 표시 항목이 검증된 statement(출처 참조 보유)에서 나옴.

## 9. 열린 질문

1. **최소 탐색 UI 프론트 스택** — FastAPI+Jinja2+HTMX(권장) vs Next.js.
2. [2] 뉴스 소스의 구체적 ToS·라이선스 — 구현 착수 전 조사 필요.

## 10. 마일스톤 재정렬

데이터 우선 + 검색 1차 출시를 반영해 `CLAUDE.md` §9 로드맵을 다음과 같이 재배치한다(상세는 거기 반영).

- **1차 (now)**: M1(타입+validation) → M2(Wikidata 시드) → M6의 일부(읽기전용 query API + 최소 탐색 UI).
- **후행**: M3(등급 분류기는 M2에 일부 내장됨, 뉴스용 본격화) → M4(뉴스 확장, §4.2) → M5(재구성형 생성, §6) → M6 확장(자연어 Q&A).
