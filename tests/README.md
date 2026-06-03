# tests

`src/` 모듈에 대응하는 테스트. M1에서는 **validation 규칙(스키마 §5)** 부터 테스트로 강제한다.

우선순위:
1. `ontology` — 출처 없는 Statement 거부, 존재하지 않는 source 참조 거부, predicate 화이트리스트, `valid_from <= valid_to` 등 (스키마 §5의 6개 규칙).
2. `grading` — `source_type` → grade 매핑, 민감 건 자동 승격 차단.
3. `generate` — 입력에 없던 사실이 출력에 생기지 않음(재구성형 보장).

스택 확정 후 테스트 러너를 정한다 (`CLAUDE.md` §7 — 미확정).
