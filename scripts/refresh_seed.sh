#!/usr/bin/env bash
# Wikidata 시드 주기적 갱신 스크립트.
# crontab/launchd에서 호출하거나 수동 실행.
#
#   # 주 1회 갱신 예: crontab에 추가
#   0 4 * * 0  /path/to/Veristar/scripts/refresh_seed.sh
#
# VERISTAR_MAX: 최대 엔티티 수 (기본 80)
# VERISTAR_SEED_PATH: 출력 경로
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MAX="${VERISTAR_MAX:-80}"
SEED="${VERISTAR_SEED_PATH:-data/seed/wikidata_seed.json}"
LOG="${ROOT}/.run/refresh_$(date +%Y%m%d_%H%M%S).log"
PYTHON="$ROOT/.venv/bin/python"

mkdir -p "$(dirname "$LOG")"

echo "[$(date)] 시드 갱신 시작 (max=$MAX)" | tee -a "$LOG"
"$PYTHON" -m veristar.ingest.wikidata.seed \
  --roots-file "$ROOT/config/roots.txt" \
  --max "$MAX" \
  --allow-unreferenced \
  --out "$SEED" 2>&1 | tee -a "$LOG"
echo "[$(date)] 완료" | tee -a "$LOG"

# 서버가 실행 중이면 재기동해 새 시드 반영
if "$ROOT/scripts/server.sh" status 2>/dev/null | grep -q "^running"; then
  echo "[$(date)] 서버 재기동..." | tee -a "$LOG"
  "$ROOT/scripts/server.sh" restart >> "$LOG" 2>&1
fi
