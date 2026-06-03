# grading — 출처 등급 분류 (파이프라인 [3])

후보 Statement의 출처를 보고 `OFFICIAL / REPORTED / RUMOR` 등급을 부여한다.

- 자동 매핑은 `source_type` 기준 (스키마 §3 매핑 표). **출발점일 뿐**이다.
- 민감 건(`sensitive=true`)은 자동 OFFICIAL 승격을 막고 **사람 검수**로 넘긴다.
- 등급 상승(REPORTED → OFFICIAL)은 **새 OFFICIAL 출처가 붙을 때만**. 자동 추론으로 올리지 않는다.

원칙: 등급은 "출처의 성격"이지 "진실 여부"가 아니다 (`CLAUDE.md` §4-2).
