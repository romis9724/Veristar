# graph — 그래프 저장소 (파이프라인 [4])

reified Statement를 저장·조회하는 저장소 인터페이스. 비즈니스 로직은 추상 인터페이스에 의존하고, 저장 구현(파일/DB)은 갈아끼울 수 있게 한다(Repository 패턴).

- 초기 구현: 파일 기반(JSON/JSONL). 규모가 커지면 Neo4j 또는 RDF 트리플스토어 검토 (`CLAUDE.md` §7).
- 적재 전 `ontology`의 validation을 통과해야 한다. 통과 못 하면 거부.
- **지우지 않는다**: 라벨이 뒤집히면 기존 Statement를 `SUPERSEDED`/`RETRACTED`로 남기고 새 Statement를 추가한다 (스키마 §2.3).

조회 인터페이스는 콘텐츠 생성이 쓸 `grade==OFFICIAL AND sensitive==false` 필터 쿼리를 1급으로 제공한다.
