# ontology — 데이터 모델 & validation (공유)

파이프라인 전 단계가 의존하는 1급 타입을 정의한다. 정의 출처는 [`docs/ontology-schema.md`](../../../docs/ontology-schema.md).

담을 것:
- `Entity` 타입 (`Person`/`Group`/`Organization`/`Work`/`Event`/`Award`) — 스키마 §1
- `Statement` (reified edge) — 스키마 §2. `grade`/`status`/`sources`/`sensitive` 포함
- `Source` — 스키마 §3
- **validation** — 스키마 §5의 6개 규칙을 코드로 강제. 위반 시 적재 거부.

원칙: "출처 없는 사실은 없다"를 타입·검증 레벨에서 강제하는 곳이 여기다 (`CLAUDE.md` §4-1).
M1의 1차 결과물.
