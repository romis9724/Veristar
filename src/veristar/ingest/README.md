# ingest — 수집기 (파이프라인 [1][2])

외부 소스에서 후보 Statement를 만든다.

- **[1] 시드**: Wikidata(CC0, 1순위) / Wikipedia → 베이스 그래프. 가능하면 Wikidata QID를 `id`로 매핑.
- **[2] 뉴스 확장**: 공개 API/RSS 우선. 사실(fact)만 추출하고 **원문 표현은 가져오지 않는다** — 출처는 URL 링크로만 보관.

여기서 강제할 것:
- 민감 카테고리(논란·사건·사생활·열애·건강·정치 등) 필터를 **파이프라인 입구에 둔다.** 뒤 단계로 새면 안 된다 (`CLAUDE.md` §8, `docs/safety-guidelines.md`).
- 네이버·다음 본문 크롤링 금지 (약관·저작권).

## wikidata/ (M2 — 구현됨)

루트 QID에서 BFS 확장하며 시드 그래프를 만든다. 계획: [`docs/plans/m2-wikidata-seed-plan.md`](../../../docs/plans/m2-wikidata-seed-plan.md).

- `mapping.py` — P31→타입, 속성·관계 매핑 (주입 가능; 기본값은 ⚠️ 라이브 대조 검증 필요)
- `mapper.py` — 순수: Wikidata 아이템 JSON → `(Entity, [Statement], [Source])`. reference 없는 claim skip, 화이트리스트 밖 속성(배우자 등) 미매핑 = 민감 필터
- `client.py` — `WikidataClient`(Protocol) + `HttpWikidataClient`(httpx). 테스트는 Fake/MockTransport
- `seed.py` — scope→fetch→map→assemble→`validate_cross_references`→JSON 기록

실 시드 실행 (소규모, 루트 QID 지정):
```bash
python -m veristar.ingest.wikidata.seed --root Q494721 --max 50 --out data/seed/wikidata_seed.json
```
산출물은 M1 `load_graph()` 검증을 통과한다. reference 없는 claim까지 받으려면 `--allow-unreferenced`.
