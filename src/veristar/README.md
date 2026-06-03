# src — 모듈 맵

각 모듈은 `CLAUDE.md` §3 데이터 파이프라인의 한 단계에 대응한다.
데이터는 항상 아래 방향으로만 흐른다. 민감 카테고리 필터는 **입구(`ingest`)** 에서 막아 뒤 단계로 새지 않게 한다.

```
ingest ──> grading ──> graph ──> generate
   │          │          │          │
  수집      등급 부여    적재     재구성형 생성
                                  (OFFICIAL만)
        ontology = 위 전 단계가 공유하는 타입·스키마
```

| 모듈 | 파이프라인 단계 | 책임 | 핵심 제약 (`CLAUDE.md` §4) |
|---|---|---|---|
| [`ontology/`](./ontology/) | — (공유) | 엔티티·Statement·Source 데이터 모델(타입)과 validation | 출처 없는 Statement는 모델 레벨에서 거부 |
| [`ingest/`](./ingest/) | [1][2] | Wikidata/Wikipedia 시드 + 뉴스 사실 추출(원문 비복제) | 본문 복제 금지, 민감 카테고리 입구 차단 |
| [`grading/`](./grading/) | [3] | `source_type` → `OFFICIAL/REPORTED/RUMOR` 분류 | 등급은 출처 성격이지 진실 여부 아님 |
| [`graph/`](./graph/) | [4] + query | 저장소(Repository) + 조회(search·관계·연표·이웃, 출처 부착) | 적재 시 validation 통과 필수 |
| [`api/`](./api/) | query 표면 | 읽기전용 FastAPI(JSON `/api`) + HTMX 탐색 UI(`/`) | 읽기 전용, 모든 statement에 출처 등급 노출 |
| [`generate/`](./generate/) | [5] | 연표·요약 등 재구성형 콘텐츠 생성 | `OFFICIAL` & 비민감만 입력, 추론형 금지 |

스키마 정의는 [`docs/ontology-schema.md`](../../docs/ontology-schema.md), 안전 규칙은 [`docs/safety-guidelines.md`](../../docs/safety-guidelines.md)를 본다.
