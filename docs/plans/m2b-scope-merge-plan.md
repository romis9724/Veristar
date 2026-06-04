# M2b 구현 계획 — 다중 루트 scope + 증분 병합 저장소

> 목표: 시드를 여러 루트에서 모으고, 여러 실행을 **영속 그래프에 누적·병합·중복제거**한다. 재수집 시 사라진 사실은 삭제하지 않고 **SUPERSEDED** 처리(스키마 §2.3). 이게 있어야 "그래프가 자란다"가 진짜가 되고, 이후 저빈도 스케줄 갱신이 의미를 가진다.
>
> 근거: `docs/service-design.md` §4.1, `memory/data-pipeline-decisions`, Karpathy `ingest`/`lint` 의미. 방법론: TDD.

## 0. 설계 결정

| 항목 | 결정 |
|---|---|
| 저장 포맷 | 당장은 단일 JSON 그래프 유지. 병합은 포맷 독립이고 Repository 뒤라 JSONL 전환은 후일 무손실 교체(CLAUDE.md §7 방향, deferred) |
| 다중 루트 | `--root Q…` + `--roots-file <path>`(한 줄 1 QID, `#` 주석) |
| 병합 기본값 | 출력 파일 존재 시 **병합(누적)**, `--fresh`로 덮어쓰기 |
| 변경 추적 | 재수집된 출처의 기존 statement가 이번에 안 나오면 **SUPERSEDED**(보존) |

## 1. 병합 의미 (graph/merge.py)

`merge(base, incoming, reconciled_sources) -> (GraphDocument, MergeReport)`

- **엔티티·출처**: id 기준 upsert(incoming이 최신 → 우선). 중복 자동 제거.
- **statement**: id(`stmt_wd_…` 결정론적) 기준 upsert.
- **SUPERSEDED 조정**: 이번 실행에서 재수집한 출처(`reconciled_sources`, 예 `src_wd_Q…`)에 대해, base에는 있으나 incoming에 없는 statement → `status=SUPERSEDED`로 보존(삭제 금지).
- **MergeReport**: added/updated/superseded 카운트(로그용).
- 멱등성: 동일 루트·무변경 재실행 → 변화 0.

## 2. 오케스트레이션 (seed.py 확장)

```
roots = --root + --roots-file
incoming = build_seed(client, roots, …)           # 기존 BFS 수집
if 병합 and out 존재: base = load_graph(out)
   merged, report = merge(base, incoming, reconciled_sources=incoming의 출처 id집합)
else: merged = incoming
validate_cross_references(merged) → write(out)
log(report)
```

- `reconciled_sources` = incoming의 모든 source id(이번에 실제 재수집된 페이지). 그 출처에 한해서만 supersede 판정(다른 루트의 기존 데이터는 건드리지 않음).

## 3. CLI

- `--root Q1 Q2 …` (기존)
- `--roots-file path` (신규, 누적)
- `--fresh` (기존 파일 무시·덮어쓰기). 기본은 병합.
- 기존 `--max`, `--allow-unreferenced`, `--out` 유지.

## 4. TDD

- `test_merge.py`: upsert(엔티티·statement dedup), SUPERSEDED 조정(사라진 사실), 멱등성, 다른 출처 보존, 결과 validation 통과.
- `test_seed.py`: 다중 루트 수집, `--roots-file` 파싱, 병합 모드 vs `--fresh`.

## 5. 완료 기준
- [ ] `merge()` + MergeReport + 테스트.
- [ ] 다중 루트 + roots-file + 병합/fresh CLI.
- [ ] 재수집 시 사라진 사실 SUPERSEDED, 그래프 누적·중복제거 동작.
- [ ] 결과가 M1 validation 통과. ruff·mypy·pytest(80%+) green.

## 6. 범위 밖 (후행)
- 저빈도 **스케줄 갱신**(cron/launchd `--refresh`) — 본 단계 완료 후 싸게 추가.
- JSONL 저장소 전환, 뉴스(M4).
