# Veristar

> *veritas*(진실) + *star*(스타) — 출처 등급으로 검증한 연예 지식그래프와 콘텐츠 생성 시스템.

연예 도메인의 인물·그룹·소속사·작품·이벤트를 그래프로 구조화하되,
**모든 사실에 출처와 신뢰 등급을 붙이고**, "공식 확인된" 사실만 콘텐츠의 재료로 쓴다.

## 핵심 아이디어

시스템은 "이게 **진실인가**"를 판정하지 않는다. 그건 불가능하고 위험하다.
대신 "이게 **공식 출처에서 나왔는가**"라는, 객관적으로 판정 가능한 것만 판정한다.

- `OFFICIAL` — 소속사 공식발표·본인 SNS·정부/시상식·Wikidata → **콘텐츠 재료 O**
- `REPORTED` — 언론 보도, 공식 미확인 → 저장만, 재료 X
- `RUMOR` — 미검증 → 격리

## 문서

- [`CLAUDE.md`](./CLAUDE.md) — 프로젝트 상위 규칙 (Claude Code가 읽는 파일)
- [`docs/ontology-schema.md`](./docs/ontology-schema.md) — 엔티티·관계·출처 모델
- [`docs/safety-guidelines.md`](./docs/safety-guidelines.md) — 법무·윤리 가드레일
- [`docs/service-design.md`](./docs/service-design.md) — 검색+보조생성 서비스 설계 (아키텍처·데이터 수집·1차 범위)
- [`data/examples/sample.json`](./data/examples/sample.json) — 스키마 예시 데이터

## 디렉토리

```
veristar/
├── CLAUDE.md              # 프로젝트 상위 규칙 (Claude Code가 읽는 파일)
├── README.md
├── pyproject.toml         # 패키지·의존성·도구 설정
├── docs/                  # 스키마·안전 가드레일·서비스 설계
├── src/veristar/          # 파이프라인 모듈 (veristar/README.md = 모듈 맵)
│   ├── ontology/          #   ✅ M1: 공유 타입 + validation
│   ├── ingest/            #   [1][2] 수집
│   ├── grading/           #   [3] 출처 등급
│   ├── graph/             #   [4] 저장소
│   └── generate/          #   [5] 재구성형 생성
├── data/
│   ├── seed/              # Wikidata 시드
│   └── examples/          # 스키마 예시 (sample.json)
└── tests/
```

각 모듈과 데이터 파이프라인의 대응은 [`src/veristar/README.md`](./src/veristar/README.md)를 본다.

## 개발 환경

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# 품질 게이트 (lint → format → type → test+coverage)
ruff check . && ruff format --check . && mypy src && pytest
```

## 시작하기 (Claude Code)

1. 이 폴더를 프로젝트 루트로 연다.
2. Claude Code가 `CLAUDE.md`를 자동으로 컨텍스트에 올린다.
3. 진행 순서·마일스톤은 [`docs/service-design.md`](./docs/service-design.md), 구현 계획은 [`docs/plans/`](./docs/plans/)를 본다.

## 상태

🟢 **M1 완료** — 온톨로지 타입 + 스키마 §5 validation 구현([`src/veristar/ontology/`](./src/veristar/ontology/)), `sample.json` 검증 통과, 테스트 25개·커버리지 98%. 다음: **M2** Wikidata 시드 수집기. 서비스 방향은 [`docs/service-design.md`](./docs/service-design.md) — 검색 메인 + 보조 생성, 스택 Python/FastAPI/JSONL.
