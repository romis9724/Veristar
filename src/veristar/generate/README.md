# generate — 콘텐츠 생성 (파이프라인 [5])

OFFICIAL·비민감 Statement만 입력으로 받아 **재구성형(reconstructive)** 콘텐츠를 만든다.

허용 (✅): OFFICIAL 사실의 요약·정리·연표(timeline)화·번역. **새 정보 추가 없음.**
금지 (❌): 관계 추측, 미래 예측, 평가·해석 추가 등 추론형(inferential).

판단 기준 (`CLAUDE.md` §5):
> 출력에 입력 Statement에 없던 사실이 새로 생겼는가? → 생겼다면 차단.

입력 게이트: `graph`에서 `grade==OFFICIAL AND sensitive==false`로 쿼리한 결과만 받는다. REPORTED/RUMOR는 절대 입력에 넣지 않는다.
