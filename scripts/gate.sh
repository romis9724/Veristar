#!/usr/bin/env bash
# Veristar 품질 게이트 (E2E 서버 커버리지 합산판)
#
#   bash scripts/gate.sh
#
# 흐름:
#   1) ruff (lint + format)         2) mypy
#   3) 단위·통합 테스트 (e2e 제외, coverage 직접 측정)
#   4) 커버리지 계측 모드로 서버 기동 → 5) E2E(Playwright) 실행 → 6) 서버 종료
#   7) coverage combine → report (fail-under=80)
#
# 핵심: E2E는 외부 uvicorn 서버(localhost:8000)에 접속한다. 그 서버를
#       COVERAGE_PROCESS_START 환경에서 띄우면 a1_coverage.pth 훅이 자동으로
#       커버리지를 측정하고, server.sh stop(SIGTERM) 시 sigterm=true 설정으로
#       데이터를 flush한다. 단위 테스트 데이터와 combine하여 routes.py/app.py
#       (RAG·Q&A·PG 분기)까지 정직하게 집계된다.
#
# 환경변수: VERISTAR_PORT(기본 8000)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${VERISTAR_PORT:-8000}"
RUFF="$ROOT/.venv/bin/ruff"
MYPY="$ROOT/.venv/bin/mypy"
COV="$ROOT/.venv/bin/coverage"
PYTEST="$ROOT/.venv/bin/pytest"

ts() { date '+%H:%M:%S'; }
fail() { echo "[$(ts)] ✗ $1 실패"; exit 1; }

echo "[$(ts)] ====== Veristar 품질 게이트 시작 ======"

echo "[$(ts)] [1] ruff (lint + format)..."
"$RUFF" check . || fail "ruff check"
"$RUFF" format --check . || fail "ruff format"

echo "[$(ts)] [2] mypy..."
"$MYPY" src || fail "mypy"

echo "[$(ts)] [3] coverage 초기화 + 단위·통합 테스트 (e2e 제외)..."
"$COV" erase
# pytest-cov 플러그인 비활성화(-p no:cov), coverage가 직접 병렬 측정.
# addopts의 --cov/--ignore을 덮어쓰되 e2e 제외는 유지.
"$COV" run --parallel-mode -m pytest -o addopts="--ignore=tests/e2e" -p no:cov
UNIT_RC=$?
[ "$UNIT_RC" -ne 0 ] && fail "단위·통합 테스트 (rc=$UNIT_RC)"

echo "[$(ts)] [4] 커버리지 계측 모드로 서버 재시작..."
export COVERAGE_PROCESS_START="$ROOT/pyproject.toml"
# server.sh restart 는 stop→start 사이 포트 해제 레이스가 있어, 명시적으로
# 정지하고 포트가 풀릴 때까지 폴링한 뒤 기동한다.
bash scripts/server.sh stop >/dev/null 2>&1 || true
for _ in $(seq 1 20); do lsof -ti ":${PORT}" >/dev/null 2>&1 || break; sleep 0.5; done
bash scripts/server.sh start || fail "서버 기동"
# health 대기 (Ollama 초기화 여유 포함)
ready=0
for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" -ne 1 ] && { bash scripts/server.sh stop; fail "서버 health 미응답"; }

echo "[$(ts)] [5] E2E (Playwright, 서버 커버리지 수집)..."
"$PYTEST" -o addopts="" -p no:cov tests/e2e
E2E_RC=$?

echo "[$(ts)] [6] 서버 종료 (SIGTERM → coverage flush)..."
bash scripts/server.sh stop
for _ in $(seq 1 20); do lsof -ti ":${PORT}" >/dev/null 2>&1 || break; sleep 0.5; done
sleep 1
unset COVERAGE_PROCESS_START

echo "[$(ts)] [7] coverage combine + report..."
"$COV" combine || fail "coverage combine"
"$COV" report --show-missing
REPORT_RC=$?

[ "$E2E_RC" -ne 0 ] && fail "E2E 테스트 (rc=$E2E_RC)"
[ "$REPORT_RC" -ne 0 ] && fail "커버리지 80% 미달"

echo "[$(ts)] ====== ✓ 품질 게이트 통과 ======"
