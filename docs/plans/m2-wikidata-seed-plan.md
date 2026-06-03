# M2 구현 계획 — Wikidata 시드 수집기

> 목표: Wikidata에서 도메인 한정 엔티티를 긁어 **M1 ontology 타입(Entity·Source·Statement)으로 매핑**하고, validation을 통과하는 시드 그래프(`data/seed/`)를 만든다. 이것이 M6a 검색이 올라갈 실데이터 백본이다.
>
> 근거: `docs/service-design.md` §4.1, `docs/safety-guidelines.md`(CC0·민감 제외). 방법론: TDD.

---

## 0. 핵심 설계 원칙

1. **순수 매핑 ↔ 네트워크 분리.** 매핑 로직(Wikidata JSON → 타입)은 순수 함수로 테스트하고, HTTP는 얇은 클라이언트(Protocol 뒤)로 분리한다. → 테스트는 **픽스처 JSON으로만, 네트워크 없이** 돈다.
2. **산출물은 M1 validation을 통과해야 한다.** seed 출력은 `load_graph()`로 자기검증한다.
3. **민감 필터 = 속성 화이트리스트.** 매핑하는 P-속성만 받고 나머지(배우자 P26, 파트너 P451 등 관계·사생활)는 **아예 매핑하지 않는다**. 입구 차단(`CLAUDE.md` §8).
4. **보수적 등급.** Wikidata claim 중 **레퍼런스가 달린 것만** OFFICIAL(WIKIDATA_VERIFIED)로 받는다(service-design §4.1 정제 규칙).

## 1. 데이터 획득 방식

```
[scope] SPARQL(WDQS)로 도메인 한정 → QID 집합
   ↓
[fetch] 각 QID의 전체 엔티티 JSON (Special:EntityData/Q###.json)
        → claims·qualifiers·references 포함
   ↓
[map]   순수 매퍼: 엔티티 JSON → (Entity, [Statement], [Source])
   ↓
[assemble+validate] GraphDocument 조립 → load_graph 자기검증
   ↓
[write] data/seed/wikidata_seed.json
```

- **scope를 SPARQL로, 상세를 EntityData JSON으로** 하는 이유: SPARQL은 QID 발견에 좋지만 reference(provenance) 접근이 약하다. 레퍼런스 기반 등급 판정(원칙 4)에는 엔티티 JSON이 필요.

## 2. 매핑 규칙 (mapping.py 상수)

**엔티티 타입 판정** — `P31`(instance of):
| P31 값 | EntityType |
|---|---|
| Q5(human) | Person |
| band/musical group/idol group | Group |
| record label/business/broadcaster | Organization |
| album/single/song/film/TV series | Work |
| award | Award |
| award ceremony/concert | Event |

**엔티티 속성** (공개·비민감만):
| Wikidata | 필드 |
|---|---|
| P569 birth date | Person.birth_year (연도만) |
| P27 country of citizenship | Person.nationality |
| P106 occupation | Person.occupation[] |
| P571 inception | Group.debut_date |
| P577 publication date | Work.release_date |

**관계(Statement)** — predicate 화이트리스트(스키마 §2.1) 안만:
| Wikidata | predicate |
|---|---|
| P463 member of / P527 has part | memberOf |
| P175 performer / P800 notable work | appearedIn·released |
| P162 producer / P264 record label | producedBy |
| P166 award received | wonAward |
| P1411 nominated for | nominatedFor |
| P580 start time(qualifier) | valid_from |
| P582 end time(qualifier) | valid_to |

> ⚠️ 화이트리스트에 없는 모든 속성(배우자·파트너·논란 관련 등)은 매핑하지 않는다 = 민감 필터.

## 3. 출처·등급 처리

- claim에 reference(provenance)가 있으면 → `Source(source_type=WIKIDATA_VERIFIED, publisher="Wikidata", url=엔티티 URL, license="CC0")`, grade=OFFICIAL.
- reference 없는 claim → **기본 skip**(`require_reference=True`). 설정으로 끌 수 있게.
- id 매핑: 엔티티 `id = "wd:Q###"`(QID). object가 QID면 동일 규칙, 리터럴이면 그대로(hasRole 등).

## 4. 모듈 구조 (src/veristar/ingest/wikidata/)

```
ingest/wikidata/
├── __init__.py
├── client.py     # WikidataClient(Protocol) + HttpWikidataClient(httpx): sparql(), fetch_entity()
├── mapping.py    # P31→type, 속성·관계 매핑 상수 (QID 상수 포함)
├── mapper.py     # 순수: entity_json → (Entity, [Statement], [Source]) — 테스트 핵심
└── seed.py       # 오케스트레이션: scope→fetch→map→assemble→validate→write. __main__ 진입점
```

- 의존성 추가: **httpx** (런타임). pyproject에 반영.
- 클라이언트는 Protocol로 추상화 → 테스트는 FakeWikidataClient 주입(네트워크 0).

## 5. TDD 순서

1. `test_mapper.py` — 픽스처 엔티티 JSON(사람 1·그룹 1)으로:
   - P31→올바른 EntityType, 속성 매핑(birth_year/occupation 등)
   - 관계 매핑(memberOf 등)과 qualifier→valid_from/to
   - reference 없는 claim skip, **민감 속성(P26 등) 미매핑** 확인
   - 모든 산출 Statement가 OFFICIAL·WIKIDATA_VERIFIED source 참조
2. `test_seed.py` — FakeWikidataClient로 오케스트레이션 → 결과 GraphDocument가 `validate_cross_references()==[]`, `load_graph` 통과.
3. `test_client.py` — SPARQL/EntityData URL·파라미터 조립만 검증(HTTP 모킹), 실호출 없음.

## 6. 완료 기준 (DoD)

- [ ] `mapper`: P31 타입 판정 + 속성·관계 매핑 + reference 필터 + 민감 속성 제외.
- [ ] `client`: SPARQL scope 쿼리 + EntityData fetch (Protocol + httpx 구현).
- [ ] `seed`: scope→fetch→map→assemble→**load_graph 자기검증**→`data/seed/wikidata_seed.json` 기록.
- [ ] 픽스처 기반 테스트(네트워크 0), 커버리지 80%+, ruff·mypy green.
- [ ] 실 시드 1회 실행법 문서화(소규모 scope) — 실행 자체는 수동/선택.

## 6.5 라이브 검증 결과 (2026-06-04, Stray Kids Q46134670)

실 시드 1회 실행으로 두 가지 설계 오류를 발견·교정했다(픽스처만으로는 못 잡음):

1. **P527(has part)은 statement로 만들지 않는다.** 방향이 그룹→멤버라 `memberOf`(Person→Group)와 반대고, "group of awards" 같은 비그룹에도 붙어 과적용된다. → **확장 힌트(expansion_props)로만** 쓰고, `memberOf` 엣지는 멤버 본인의 P463에서 생성.
2. **확장은 statement object + 확장 힌트 object 양쪽을 따라간다.** (역방향 노드가 subject에 있어 `object`만 따라가면 멤버가 누락됨.)
3. **타입 QID를 라이브로 검증·확장**했다(`mapping.py`의 `[verified]` 주석). best-effort 값만으론 다수가 "type not resolved"로 누락됐었다.

또한 K-pop claim은 **대부분 reference가 없어** `require_reference=True`(기본)면 엣지가 거의 안 생긴다. 실용 시드는 `--allow-unreferenced` 필요 → 기본 정책 재검토 여지(열린 질문).

결과(`--max 60 --allow-unreferenced`): 57 엔티티(Group 1·Person 9·Work 4·Award 43), 33 statements, 위반 0.

## 7. 범위 밖
- 등급 분류기 본체(M3), 뉴스(M4), 생성(M5), API/UI(M6a). M2는 **Wikidata → 검증된 시드 JSON**까지.

## 8. 열린 질문 (착수 전 결정)
1. **시드 scope**: 첫 ~수십 개를 어떻게 고를까 — (a) 명시적 루트 QID 몇 개(그룹 1~3 + 멤버·직접관계)에서 확장(권장: 통제·소규모) vs (b) SPARQL 조건 쿼리(occupation+nationality)로 광범위.
2. **require_reference 기본값**: reference 없는 claim skip(권장, 보수적) vs 전부 OFFICIAL 수용(커버리지↑·위험↑).
3. **HTTP 라이브러리**: httpx(권장) vs requests vs SPARQLWrapper.
4. **출력 포맷**: 검증된 단일 JSON(권장, M1 재사용) vs 지금부터 JSONL.
