# generate — 콘텐츠 생성 (파이프라인 [5])

OFFICIAL·비민감 Statement만 입력으로 받아 **재구성형(reconstructive)** 콘텐츠를 만든다.

허용 (✅): OFFICIAL 사실의 요약·정리·연표(timeline)화·번역. **새 정보 추가 없음.**
금지 (❌): 관계 추측, 미래 예측, 평가·해석 추가 등 추론형(inferential).

판단 기준 (`CLAUDE.md` §5):
> 출력에 입력 Statement에 없던 사실이 새로 생겼는가? → 생겼다면 차단.

입력 게이트: `graph`에서 `grade==OFFICIAL AND sensitive==false`로 쿼리한 결과만 받는다. REPORTED/RUMOR는 절대 입력에 넣지 않는다.

## 모듈
- `reconstructive.py` — 연표·요약 텍스트(순수 로직, LLM 불필요).
- `qa.py` — 자연어 Q&A(GraphRAG). 그래프 OFFICIAL 사실만 근거로 제공, 추론 금지.
- `llm.py` — **로컬 Ollama(qwen3) 클라이언트**(httpx). 앤트로픽 API 미사용. `OLLAMA_HOST`·`VERISTAR_LLM_MODEL`(기본 `qwen3:14b`)로 설정. 미연결 시 graceful 오류.
