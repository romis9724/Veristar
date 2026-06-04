#!/usr/bin/env bash
# Veristar 탐색 서버(uvicorn) 관리: start | stop | restart | status
#
#   ./scripts/server.sh start      # 백그라운드 기동
#   ./scripts/server.sh stop       # 종료
#   ./scripts/server.sh restart    # 재시작
#   ./scripts/server.sh status     # 상태
#
# 환경변수로 조정: VERISTAR_HOST(기본 127.0.0.1) · VERISTAR_PORT(기본 8000)
#                  VERISTAR_SEED_PATH(기본 data/seed/wikidata_seed.json)
#                  VERISTAR_REFRESH_INTERVAL_HOURS(기본 24, 0=비활성)
#                  VERISTAR_ROOTS_FILE(기본 config/roots.txt)
#                  VERISTAR_MAX(기본 80)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOST="${VERISTAR_HOST:-127.0.0.1}"
PORT="${VERISTAR_PORT:-8000}"
SEED="${VERISTAR_SEED_PATH:-data/seed/wikidata_seed.json}"
REFRESH="${VERISTAR_REFRESH_INTERVAL_HOURS:-24}"
APP="veristar.api.app:create_default_app"
UVICORN="$ROOT/.venv/bin/uvicorn"
RUNDIR="$ROOT/.run"
PIDFILE="$RUNDIR/server.pid"
LOGFILE="$RUNDIR/server.log"

mkdir -p "$RUNDIR"

is_running() {
  [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

start() {
  if is_running; then
    echo "이미 실행 중 (PID $(cat "$PIDFILE")) → http://$HOST:$PORT"
    return 0
  fi
  if [[ ! -x "$UVICORN" ]]; then
    echo "✗ uvicorn 없음: $UVICORN"
    echo "  먼저: python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'"
    exit 1
  fi
  if [[ ! -f "$SEED" ]]; then
    echo "✗ 시드 파일 없음: $SEED"
    echo "  먼저 생성: python -m veristar.ingest.wikidata.seed --root Q46134670 --max 60 --allow-unreferenced"
    exit 1
  fi
  # 포트 선점 확인(스크립트 밖에서 띄운 서버 등)
  if lsof -ti ":$PORT" >/dev/null 2>&1; then
    echo "✗ 포트 $PORT 가 이미 사용 중입니다. './scripts/server.sh stop' 후 다시 시도하세요."
    exit 1
  fi
  VERISTAR_SEED_PATH="$SEED" \
  VERISTAR_REFRESH_INTERVAL_HOURS="$REFRESH" \
  nohup "$UVICORN" --factory "$APP" \
    --host "$HOST" --port "$PORT" >"$LOGFILE" 2>&1 &
  echo $! >"$PIDFILE"
  sleep 1
  if is_running; then
    echo "✓ started → http://$HOST:$PORT  (PID $(cat "$PIDFILE"), log: $LOGFILE)"
    [[ "$REFRESH" != "0" ]] && echo "  자동 갱신: ${REFRESH}시간마다 (VERISTAR_REFRESH_INTERVAL_HOURS=$REFRESH)"
  else
    echo "✗ 기동 실패. 로그 확인: $LOGFILE"
    tail -n 15 "$LOGFILE" 2>/dev/null || true
    rm -f "$PIDFILE"
    exit 1
  fi
}

stop() {
  if is_running; then
    local pid
    pid="$(cat "$PIDFILE")"
    kill "$pid" 2>/dev/null || true
    rm -f "$PIDFILE"
    echo "✓ stopped (PID $pid)"
    return 0
  fi
  # PID 파일이 없거나 죽은 경우: 포트 점유 프로세스를 정리(폴백)
  local pids
  pids="$(lsof -ti ":$PORT" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill 2>/dev/null || true
    echo "✓ stopped (포트 $PORT 점유 프로세스 정리)"
  else
    echo "실행 중이 아닙니다."
  fi
  rm -f "$PIDFILE"
}

status() {
  if is_running; then
    echo "running (PID $(cat "$PIDFILE")) → http://$HOST:$PORT"
  elif lsof -ti ":$PORT" >/dev/null 2>&1; then
    echo "running (PID 파일 밖, 포트 $PORT 점유 중)"
  else
    echo "stopped"
  fi
}

case "${1:-}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; sleep 1; start ;;
  status)  status ;;
  *) echo "usage: $0 {start|stop|restart|status}"; exit 1 ;;
esac
