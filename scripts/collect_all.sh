#!/usr/bin/env bash
# Veristar 멀티소스 전체 수집 스크립트
# cron 예시: 0 3 * * * cd /path/to/veristar && bash scripts/collect_all.sh >> .run/collect.log 2>&1
#
# 환경변수:
#   VERISTAR_VAULT      vault 루트 (기본 vault/)
#   VERISTAR_CONFIG     celebrities.yaml 경로 (기본 config/celebrities.yaml)
#   VERISTAR_FEEDS      news_feeds.yaml 경로 (기본 config/news_feeds.yaml)
#   VERISTAR_SEED       시드 JSON 경로 (기본 data/seed/wikidata_seed.json)
#   SOURCES             수집 소스 (기본 wikipedia,namuwiki,news)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VAULT="${VERISTAR_VAULT:-vault}"
CONFIG="${VERISTAR_CONFIG:-config/celebrities.yaml}"
FEEDS="${VERISTAR_FEEDS:-config/news_feeds.yaml}"
SEED="${VERISTAR_SEED:-data/seed/wikidata_seed.json}"
SOURCES="${SOURCES:-wikipedia,namuwiki,news}"
PYTHON="$ROOT/.venv/bin/python"
LOGDIR="$ROOT/.run"
mkdir -p "$LOGDIR"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "[$(ts)] ====== Veristar 수집 시작 ======"
echo "[$(ts)] 소스: $SOURCES | vault: $VAULT | 대상: $CONFIG"

# 1) 멀티소스 수집 (Wikipedia·나무위키·뉴스)
echo "[$(ts)] [1] 멀티소스 수집 중..."
"$PYTHON" -m veristar.ingest.collectors.runner \
  --config "$CONFIG" \
  --vault  "$VAULT" \
  --feeds  "$FEEDS" \
  --sources "$SOURCES" \
  && echo "[$(ts)] [1] 수집 완료" \
  || echo "[$(ts)] [1] 수집 부분 실패 (계속)"

# 2) Wikidata 시드 갱신·병합
echo "[$(ts)] [2] Wikidata 시드 갱신 중..."
"$PYTHON" -m veristar.ingest.wikidata.seed \
  --roots-file config/roots.txt \
  --max 120 \
  --allow-unreferenced \
  && echo "[$(ts)] [2] 시드 갱신 완료" \
  || echo "[$(ts)] [2] 시드 갱신 실패 (계속)"

# 3) LLM 검증 (UNVERIFIED → HIGH/MEDIUM/LOW)
echo "[$(ts)] [3] LLM 검증 중..."
"$PYTHON" -m veristar.verify.pipeline \
  --vault "$VAULT" \
  && echo "[$(ts)] [3] 검증 완료" \
  || echo "[$(ts)] [3] 검증 실패 (계속)"

# 4) HIGH docs → 그래프 승격
echo "[$(ts)] [4] 그래프 승격 중..."
"$PYTHON" -m veristar.verify.graph_sync \
  --vault "$VAULT" \
  --seed  "$SEED" \
  && echo "[$(ts)] [4] 승격 완료" \
  || echo "[$(ts)] [4] 승격 실패 (계속)"

# 5) PostgreSQL 마이그레이션 동기화
echo "[$(ts)] [5] PostgreSQL 동기화 중..."
"$PYTHON" -m veristar.db.migrate \
  --seed  "$SEED" \
  --vault "$VAULT" \
  && echo "[$(ts)] [5] PG 동기화 완료" \
  || echo "[$(ts)] [5] PG 동기화 실패 (계속)"

# 6) 서버가 실행 중이면 핫 리로드 신호
if [ -f "$ROOT/.run/server.pid" ] && kill -0 "$(cat "$ROOT/.run/server.pid")" 2>/dev/null; then
  echo "[$(ts)] [6] 서버 재시작..."
  bash "$ROOT/scripts/server.sh" restart
fi

echo "[$(ts)] ====== 수집 완료 ======"
