# Veristar — 온톨로지 스키마

이 문서는 Veristar 지식그래프의 데이터 모델을 정의한다.
핵심 설계 사상은 **provenance-first(출처 우선)**: 모든 사실은 독립된 출처·등급·시점을 가진 *Statement*로 표현한다.

---

## 0. 설계 핵심: 왜 "Statement"를 따로 두는가

보통 그래프는 `(주어)-[관계]->(목적어)` 트리플로 끝낸다. 하지만 Veristar는
"이 관계를 **누가/언제/어디서 주장했고, 얼마나 믿을 만한가**"가 본질이다.
그래서 관계(엣지)를 그냥 두지 않고 **Statement 노드로 reify(사물화)** 한다.

```
(Person:차은우) ──asserts──> [Statement] ──about──> (Group:아스트로)
                                  │  predicate: memberOf
                                  │  grade: OFFICIAL
                                  │  source: 소속사 공식발표
                                  │  valid_from: 2016-02
                                  └  status: ACTIVE
```

이렇게 하면 같은 관계라도 출처별로 등급을 따로 매기고, 시간이 지나 라벨이 뒤집혀도
이전 Statement를 `SUPERSEDED`로 남긴 채 새 Statement를 추가할 수 있다. (연예 정보의 필수 요건)

---

## 1. 엔티티 (Nodes)

모든 엔티티는 공통 필드를 가진다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | string | 전역 고유 ID. 가능하면 Wikidata QID 매핑 (예: `wd:Q...`) |
| `type` | enum | 아래 엔티티 타입 |
| `name` | string | 대표 명칭 |
| `aliases` | string[] | 이명·영문명·예명 |
| `created_at` | datetime | 레코드 생성 시각 |

### 엔티티 타입

| type | 설명 | 주요 속성 |
|---|---|---|
| `Person` | 개인 (가수·배우 등) | `birth_year`(공개된 경우만), `occupation[]`, `nationality` |
| `Group` | 그룹·유닛 | `debut_date`, `group_type`(band/idol/duo…) |
| `Organization` | 소속사·레이블·방송사·배급사 | `org_role`(agency/label/broadcaster…) |
| `Work` | 작품 (추상) | `work_type`(album/song/film/tv/variety…), `release_date` |
| `Event` | 시상식·콘서트·공식 행사 | `event_date`, `event_type` |
| `Award` | 상(賞) 자체 | `award_category` |
| `Source` | 출처 (별도 정의, §3) | — |

> **주의:** `birth_year`, `nationality` 등 개인정보성 속성은 **공식/공개된 정보만** 저장한다.
> 사생활·건강·관계상태 등 민감 속성은 스키마에 두지 않는다. (의도적 누락)

---

## 2. Statement (Reified Edge)

관계는 모두 Statement로 표현한다. 이것이 그래프의 1급 시민이다.

```jsonc
{
  "id": "stmt_0001",
  "subject": "wd:Q494721",        // 엔티티 id
  "predicate": "memberOf",        // §2.1 관계 어휘
  "object": "wd:Q19601036",       // 엔티티 id (또는 리터럴)
  "grade": "OFFICIAL",            // §2.2 신뢰 등급
  "status": "ACTIVE",             // §2.3 상태
  "sources": ["src_0007"],        // §3 출처 참조 (1개 이상 필수)
  "valid_from": "2016-02-23",     // 관계 시작 시점 (선택)
  "valid_to": null,               // 종료 시점. null이면 현재 유효
  "asserted_at": "2016-02-23",    // 출처가 이 사실을 말한 시점
  "sensitive": false,             // 민감 카테고리 플래그 (true면 생성에서 제외)
  "qualifier": null               // 같은 (subject,predicate,object) 구분용 보조 라벨 (선택)
}
```

> `qualifier`: 동일한 주어·관계·목적어가 여러 번 성립할 때(예: 같은 상을 다른 해/부문으로 여러 번 수상) 이를 구분하는 **출처 제공 보조 라벨**이다. 예: 수상 부문("Best New Artist"), 배역명. 추론으로 만들어내지 않는다(§4-4). 연도 구분은 `valid_from`(수상 시점)으로 표현한다.

### 2.1 관계 어휘 (predicate)

스코프는 **공식 활동 사실**로 한정한다. 사건·사생활·추측 관계는 어휘에 넣지 않는다.

| predicate | subject → object | 의미 |
|---|---|---|
| `memberOf` | Person → Group | 그룹 소속 |
| `affiliatedWith` | Person/Group → Organization | 소속사 계약 관계 |
| `appearedIn` | Person → Work | 작품 출연/참여 |
| `released` | Person/Group → Work | 음반·곡 발매 |
| `producedBy` | Work → Organization | 제작·배급 주체 |
| `collaboratedWith` | Person ↔ Person | **공식 콜라보 작품이 있을 때만** |
| `nominatedFor` | Person/Work → Award | 후보 지명 |
| `wonAward` | Person/Work → Award | 수상 |
| `presentedAt` | Award → Event | 시상식 매핑 |
| `hasRole` | Person → Work | 배역/포지션 (object를 리터럴로 허용) |

> 새 predicate를 추가할 때는: (1) 공식 활동 사실인가? (2) 추측이 아닌가? (3) 민감하지 않은가? — 세 질문을 통과해야 한다.

### 2.2 신뢰 등급 (grade) — 이 프로젝트의 핵심

**진실 여부가 아니라 출처의 성격으로 정의한다.**

| grade | 의미 | 출처 예시 | 콘텐츠 재료? |
|---|---|---|---|
| `OFFICIAL` | 1차/공식 출처에서 확인됨 | 소속사 공식발표, 본인 공식 SNS, 정부·시상식 발표, Wikidata 검증 항목 | ✅ |
| `REPORTED` | 언론 보도되었으나 공식 미확인 | 단독·추측 보도. 다수 매체 교차여도 공식 확인 전이면 여기 | ❌ |
| `RUMOR` | 미검증 | 커뮤니티·익명·소문 | ❌ (저장은 가능, 별도 격리) |

핵심 규칙:
- 콘텐츠 생성기는 **`grade == OFFICIAL` AND `sensitive == false`** 인 Statement만 입력으로 받는다.
- 등급 상승(REPORTED → OFFICIAL)은 새 OFFICIAL 출처가 붙을 때만. 자동 추론으로 올리지 않는다.

### 2.3 상태 (status) — 라벨 변경 추적

연예 정보는 "사실무근"이 나중에 "사실"로 뒤집힌다. 이를 데이터로 다룬다.

| status | 의미 |
|---|---|
| `ACTIVE` | 현재 유효 |
| `SUPERSEDED` | 더 새로운/상위 Statement로 대체됨 (기록은 보존) |
| `RETRACTED` | 출처가 철회/정정함 |

원칙: **지우지 않고 상태로 표시한다.** 변화 이력 자체가 자산이자 검증 근거다.

---

## 3. Source (출처)

Statement가 가리키는 출처. 등급 판정의 근거다.

```jsonc
{
  "id": "src_0007",
  "source_type": "OFFICIAL_ANNOUNCEMENT", // 아래 enum
  "publisher": "소속사명 / 매체명 / Wikidata",
  "url": "https://...",                    // 원문 링크 (본문 복제 X)
  "title": "...",                          // 기사/발표 제목까지만
  "published_at": "2016-02-23",
  "retrieved_at": "2026-06-04",
  "license": "CC0 / news-link-only / ..."  // 재사용 가능 범위 표시
}
```

### source_type → 기본 등급 매핑

| source_type | 기본 grade |
|---|---|
| `OFFICIAL_ANNOUNCEMENT` (소속사 공식) | OFFICIAL |
| `ARTIST_OFFICIAL_SNS` (본인 공식 계정) | OFFICIAL |
| `GOV_OR_AWARD_BODY` (정부·시상식 주관) | OFFICIAL |
| `WIKIDATA_VERIFIED` | OFFICIAL |
| `PRESS` (언론 보도) | REPORTED |
| `COMMUNITY_OR_ANON` | RUMOR |

> 자동 매핑은 **출발점**일 뿐이다. 민감 건(`sensitive=true`)은 자동 OFFICIAL 승격을 막고 사람 검수로 넘긴다.

---

## 4. VaultDoc (raw 수집 콘텐츠)

Knowledge graph 아래에 **수집 원본 레이어**가 존재한다. (`vault/store.py`)

```jsonc
{
  "id": "wikipedia-ko-방탄소년단",
  "title": "방탄소년단 (Wikipedia KO)",
  "content": "...",               // Markdown 본문 (원문 또는 변환)
  "source_type": "wikipedia",    // wikipedia | namuwiki | news | youtube | instagram | twitter
  "source_url": "https://...",
  "entity_refs": ["방탄소년단"],  // 연관 엔티티 slug
  "published": "2026-06-04",
  "retrieved": "2026-06-04",
  "confidence": "unverified",    // unverified | low | medium | high
  "license": "CC BY-SA 4.0",
  "sensitive": false,            // true여도 저장. 생성·API에서만 차단.
  "extra": {}                    // source별 추가 메타
}
```

### confidence 레벨 (LLM cross-check 결과)

| 레벨 | 의미 | 조치 |
|---|---|---|
| `unverified` | 수집 직후 초기값 | verify/pipeline.py 처리 대기 |
| `high` | 공식 출처·구체 사실·교차 검증 가능 | 그래프 승격 (graph_sync.py) |
| `medium` | 부분 신뢰, 확인 필요 | 사람 검토 큐 |
| `low` | 루머·추측·미확인 | 폐기 (재수집 필요) |

> **VaultDoc은 Statement와 독립적이다.** vault는 raw 수집 레이어이며, graph_sync.py가 HIGH 문서에서 사실을 추출해 Statement를 만든다. 직접 생성 입력으로 쓰지 않는다.

---

## 5. PostgreSQL 스키마

`src/veristar/db/schema.sql` 참조. 주요 테이블:

| 테이블 | 대응 모델 | 비고 |
|---|---|---|
| `entities` | Entity 서브타입 | `embedding vector(768)` 포함 |
| `statements` | Statement | subject·object 소프트 참조 |
| `sources` | Source | |
| `vault_docs` | VaultDoc | `embedding vector(768)` 포함 |

벡터 인덱스: IVFFlat (행 100개 이상 시 활성화 권장).

---

## 6. 전체 예시 그래프

`data/examples/sample.json` 참조. 구조 요약:

```
Entities:   [Person, Group, Organization, Work, Event, Award]
Statements: 각 관계 = 1 Statement (grade·source·valid_from 포함)
Sources:    각 Statement가 참조하는 출처 레코드
VaultDocs:  수집 원본 Markdown (confidence 분류 후 그래프 승격)
```

---

## 7. Validation 규칙 (코드로 강제)

데이터 적재 시 아래를 검사한다. 하나라도 위반하면 **거부**한다.

1. 모든 Statement는 `sources` 배열에 1개 이상 source id를 가진다.
2. 참조된 source id는 실제로 존재한다.
3. `grade`는 source의 `source_type`이 허용하는 등급과 모순되지 않는다.
4. `predicate`는 §2.1 허용 목록 안에 있다.
5. `sensitive == true`인 Statement는 생성 파이프라인 입력 쿼리에서 자동 제외된다.
6. `valid_to`가 있으면 `valid_from <= valid_to`.

---

## 8. 의도적으로 넣지 않은 것 (Out of Scope)

아래는 **일부러 모델링하지 않는다.** 추가 요청이 와도 §safety-guidelines를 근거로 재검토한다.

- 열애·결혼 등 관계 추측 (공식 발표 전)
- 사건·논란·구설·법적 분쟁
- 건강·정신건강·신체 정보
- 정치·종교 성향
- 평가·랭킹·"누가 더 인기" 류 주관적 판단
- 미래 예측 (재계약 여부, 컴백 시점 추측 등)
