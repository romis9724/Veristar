# M1 구현 계획 — 온톨로지 타입 + validation

> 목표: `docs/ontology-schema.md`의 데이터 모델(엔티티·Statement·Source)을 Python 타입으로 구현하고, 스키마 §5의 6개 validation 규칙을 **코드로 강제**한다. 이것이 그래프의 데이터 계약을 고정해 이후 M2(수집)·M6a(검색)가 의존할 토대가 된다.
>
> 방법론: TDD (`rules/common/testing.md`) — 규칙별 테스트 먼저(RED) → 구현(GREEN) → 커버리지 80%+.

---

## 0. 결정 사항 (계획 전제)

| 항목 | 선택 | 근거 |
|---|---|---|
| validation 라이브러리 | **Pydantic v2** | 스키마 기반 검증·직렬화·JSON 파싱 일괄 처리. FastAPI(M6a)와 자연 연속. `rules`의 "schema-based validation" 권장과 일치 |
| 엔티티 모델링 | **discriminated union** (`type` 태그) | Person/Group/… 별 속성을 타입별로 정밀 검증. Pydantic v2 네이티브 지원 |
| 패키지 레이아웃 | **src-layout + `veristar` 패키지** (아래 §1) | `import ontology` 같은 일반명 충돌 방지, 표준 패키징. ⚠️ CLAUDE.md §6 트리와 한 겹 달라짐 → 확인 필요 |
| 에러 처리 | **violation 수집 후 일괄 보고** | 배치 적재에 유용. fail-fast보다 디버깅 쉬움 |

---

## 1. 패키지 레이아웃

현재 `src/ontology/` 등은 README만 있는 문서 골격이다. M1에서 실제 Python 패키지로 만든다.

```
veristar/
├── pyproject.toml            # 신규: 메타·의존성·ruff/mypy/pytest 설정
├── src/
│   └── veristar/             # 신규: 최상위 패키지 (import veristar.ontology …)
│       ├── __init__.py
│       └── ontology/
│           ├── __init__.py
│           ├── enums.py      # EntityType, Predicate, Grade, Status, SourceType
│           ├── grading.py    # source_type → 허용 grade 매핑 (validation 규칙 3이 사용)
│           ├── models.py     # Entity(union), Source, Statement (Pydantic)
│           ├── graph.py      # GraphDocument 컨테이너 + 교차참조 validation
│           └── query.py      # official_nonsensitive() 등 게이트 쿼리 (규칙 5)
└── tests/
    └── ontology/
        ├── test_models.py        # 규칙 1·4·6 (모델 레벨)
        ├── test_graph_validation.py  # 규칙 2·3 (교차참조)
        ├── test_query.py         # 규칙 5 (생성 입력 게이트)
        └── test_sample_fixture.py    # data/examples/sample.json 로드·검증
```

> ⚠️ **확인 필요**: 기존 `src/ontology/README.md`(및 ingest/grading/graph/generate README)는 `src/veristar/<모듈>/`로 옮길지, 아니면 `src/<모듈>` 평면 레이아웃을 유지하고 패키지명을 두지 않을지. 권장 = `veristar` 패키지로 이동(README도 함께). CLAUDE.md §6 트리는 그에 맞춰 갱신.

## 2. 타입 정의 (models.py / enums.py)

`docs/ontology-schema.md` §1~3을 그대로 옮긴다.

- **enums.py**: `EntityType`(Person/Group/Organization/Work/Event/Award), `Predicate`(§2.1의 10종), `Grade`(OFFICIAL/REPORTED/RUMOR), `Status`(ACTIVE/SUPERSEDED/RETRACTED), `SourceType`(6종).
- **Source**: id, source_type, publisher, url, title, published_at, retrieved_at, license.
- **Entity**: 공통 필드(id, type, name, aliases, created_at) + discriminated union 하위타입:
  - Person(birth_year?, occupation[], nationality?), Group(debut_date, group_type), Organization(org_role), Work(work_type, release_date), Event(event_date, event_type), Award(award_category).
  - 민감 속성(사생활·건강·관계)은 **스키마에 두지 않는다**(§1 주의) — 모델에 필드 자체를 만들지 않는 것으로 강제.
- **Statement**: id, subject, predicate, object, grade, status, sources[], valid_from?, valid_to?, asserted_at, sensitive(기본 False).

## 3. Validation 규칙 매핑 (스키마 §5)

| 규칙 | 내용 | 구현 위치 | 방식 |
|---|---|---|---|
| 1 | Statement는 source ≥1개 | `Statement.sources` | Pydantic `min_length=1` |
| 4 | predicate는 화이트리스트 | `Statement.predicate` | `Predicate` enum이 자동 강제 |
| 6 | valid_to 있으면 valid_from ≤ valid_to | `Statement` | model_validator |
| 2 | 참조된 source id가 실재 | `GraphDocument` | 교차참조 검사 (전체 그래프 필요) |
| 3 | grade가 source_type 허용 등급과 모순 없음 | `GraphDocument` + `grading.py` | 참조 source 조회 후 매핑 비교 |
| 5 | sensitive=true는 생성 입력에서 자동 제외 | `query.py` | 적재 검증이 아닌 **쿼리 게이트** — `official_nonsensitive()` |

- **GraphDocument**: `{entities, sources, statements}` (sample.json 구조와 1:1). `validate_graph() -> list[Violation]` 가 규칙 2·3 위반을 모아 반환. `load_graph(path)` 는 위반이 있으면 예외.
- **grading.py**: `SOURCE_TYPE_DEFAULT_GRADE` 매핑 + `is_grade_allowed(source_type, grade)`. (규칙 3과 M3 분류기가 공유)
- **규칙 3 해석**: WIKIDATA_VERIFIED·OFFICIAL_ANNOUNCEMENT 등은 OFFICIAL 허용. PRESS는 REPORTED가 상한(OFFICIAL 부여 시 위반). 정확한 "허용 집합"은 구현 시 §3 매핑표 기준으로 표로 못 박는다.

## 4. TDD 순서

각 규칙마다 **통과 케이스 + 위반 케이스** 테스트를 먼저 작성한다.

1. `test_sample_fixture.py` — `data/examples/sample.json`이 검증 통과 (골든). → 모델·GraphDocument 최소 구현.
2. `test_models.py` — 규칙 1(source 0개 거부)·4(미허용 predicate 거부)·6(valid_from>valid_to 거부).
3. `test_graph_validation.py` — 규칙 2(없는 source id 참조 거부)·3(PRESS인데 OFFICIAL 부여 거부).
4. `test_query.py` — 규칙 5(sensitive=true·REPORTED·RUMOR가 `official_nonsensitive()` 결과에서 빠짐).
5. 직렬화 라운드트립(모델→JSON→모델 동일성).

## 5. 도구·스캐폴딩 (pyproject.toml)

- 런타임 의존: `pydantic>=2`.
- 개발 의존: `pytest`, `pytest-cov`, `mypy`, `ruff`.
- 설정: ruff(lint+format), mypy(strict), pytest(testpaths, src 경로), coverage(80% 게이트).
- 검증 커맨드: `ruff check . && ruff format --check . && mypy src && pytest --cov=veristar --cov-fail-under=80`.

## 6. 완료 기준 (DoD)

- [ ] `src/veristar/ontology` 타입 구현 (Entity union·Source·Statement·GraphDocument).
- [ ] 스키마 §5의 6개 규칙이 코드로 강제됨 (규칙별 통과/위반 테스트 존재).
- [ ] `data/examples/sample.json`이 검증 통과.
- [ ] `official_nonsensitive()` 게이트 쿼리 + 테스트.
- [ ] `ruff`·`mypy`·`pytest`(커버리지 80%+) 모두 통과.
- [ ] CLAUDE.md §6 트리를 실제 레이아웃에 맞춰 갱신.

## 7. 범위 밖 (M1 아님)

- Wikidata 수집(M2), 등급 분류기 본체(M3), 뉴스(M4), 생성(M5), API/UI(M6a).
- M1은 **타입과 규칙**만. 데이터는 sample.json 픽스처로만 검증.

## 8. 열린 질문

1. 패키지 레이아웃: `src/veristar/<모듈>` (권장) vs `src/<모듈>` 평면 유지.
2. 규칙 3의 "허용 등급 집합" 정확한 정의 — source_type별 상한/허용을 구현 시 표로 확정(§3 매핑 기반).
