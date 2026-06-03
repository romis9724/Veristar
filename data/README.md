# data

| 디렉토리 | 내용 |
|---|---|
| [`seed/`](./seed/) | Wikidata 기반 시드 데이터 (파이프라인 [1] 산출물). CC0 출처 위주. |
| [`examples/`](./examples/) | 스키마 예시. [`sample.json`](./examples/sample.json) — 엔티티·출처·Statement 전체 구조 예시. |

모든 데이터는 `docs/ontology-schema.md` 스키마를 따르고, `src/ontology`의 validation을 통과해야 한다.
민감 카테고리 데이터는 어떤 파일에도 넣지 않는다 (`docs/safety-guidelines.md`).
