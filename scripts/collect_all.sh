#!/usr/bin/env bash
# Veristar 멀티소스 전체 수집 스크립트
# cron 예시: 0 3 * * * cd /path/to/veristar && bash scripts/collect_all.sh >> .run/collect.log 2>&1
#
# 수집 대상은 PostgreSQL collection_targets (SPARQL 자동 발견). YAML 폴백 없음.
#
# 환경변수:
#   VERISTAR_VAULT      vault 루트 (기본 vault/)
#   VERISTAR_FEEDS      news_feeds.yaml 경로 (기본 config/news_feeds.yaml)
#   VERISTAR_SEED       시드 JSON 경로 (기본 data/seed/wikidata_seed.json)
#   SOURCES             수집 소스 (기본 wikipedia,namuwiki,news)
#   COLLECT_LIMIT       1회 처리할 pending 대상 수 (기본 100 — 점진 수집)
#   DISCOVER_OCCS       SPARQL 발견 직업 (기본 singer,actor,entertainer,creator,group)
#   DISCOVER_DOW        SPARQL 발견을 돌리는 요일 (0=일, 기본 0 — 주 1회)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VAULT="${VERISTAR_VAULT:-vault}"
FEEDS="${VERISTAR_FEEDS:-config/news_feeds.yaml}"
SEED="${VERISTAR_SEED:-data/seed/wikidata_seed.json}"
SOURCES="${SOURCES:-wikipedia,namuwiki,news}"
COLLECT_LIMIT="${COLLECT_LIMIT:-100}"
DISCOVER_OCCS="${DISCOVER_OCCS:-singer,actor,entertainer,creator,group}"
DISCOVER_DOW="${DISCOVER_DOW:-0}"
PYTHON="$ROOT/.venv/bin/python"
LOGDIR="$ROOT/.run"
mkdir -p "$LOGDIR"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "[$(ts)] ====== Veristar 수집 시작 ======"
echo "[$(ts)] 소스: $SOURCES | vault: $VAULT | limit: $COLLECT_LIMIT"

# 0) 주 1회(DISCOVER_DOW 요일) SPARQL 자동 발견 → collection_targets 보충
if [ "$(date +%w)" = "$DISCOVER_DOW" ]; then
  echo "[$(ts)] [0] SPARQL 수집 대상 발견 중 ($DISCOVER_OCCS)..."
  "$PYTHON" -m veristar.ingest.wikidata.discover \
    --occupations "$DISCOVER_OCCS" \
    && echo "[$(ts)] [0] 발견 완료" \
    || echo "[$(ts)] [0] 발견 실패 (계속)"
fi

# 1) 멀티소스 수집 (collection_targets pending 중 LIMIT건)
echo "[$(ts)] [1] 멀티소스 수집 중 (pending $COLLECT_LIMIT건)..."
"$PYTHON" -m veristar.ingest.collectors.runner \
  --vault  "$VAULT" \
  --feeds  "$FEEDS" \
  --sources "$SOURCES" \
  --limit  "$COLLECT_LIMIT" \
  && echo "[$(ts)] [1] 수집 완료" \
  || echo "[$(ts)] [1] 수집 부분 실패 (계속)"

# 2) 수집 직후 즉시 PG 동기화 (vault_docs를 API·벡터검색에 바로 반영)
#    임베딩은 embedding IS NULL인 신규 문서만 생성 → 마지막 [6]과 비용 중복 없음
echo "[$(ts)] [2] 수집분 PG 동기화 중..."
"$PYTHON" -m veristar.db.migrate \
  --seed  "$SEED" \
  --vault "$VAULT" \
  --embed \
  && echo "[$(ts)] [2] 수집분 PG 동기화 완료" \
  || echo "[$(ts)] [2] 수집분 PG 동기화 실패 (계속)"

# 3) Wikidata 시드 갱신·병합
echo "[$(ts)] [3] Wikidata 시드 갱신 중..."
"$PYTHON" -m veristar.ingest.wikidata.seed \
  --roots-file config/roots.txt \
  --max 120 \
  --allow-unreferenced \
  && echo "[$(ts)] [3] 시드 갱신 완료" \
  || echo "[$(ts)] [3] 시드 갱신 실패 (계속)"

# 4) LLM 검증 (UNVERIFIED → HIGH/MEDIUM/LOW)
echo "[$(ts)] [4] LLM 검증 중..."
"$PYTHON" -m veristar.verify.pipeline \
  --vault "$VAULT" \
  && echo "[$(ts)] [4] 검증 완료" \
  || echo "[$(ts)] [4] 검증 실패 (계속)"

# 5) HIGH docs → 그래프 승격
echo "[$(ts)] [5] 그래프 승격 중..."
"$PYTHON" -m veristar.verify.graph_sync \
  --vault "$VAULT" \
  --seed  "$SEED" \
  && echo "[$(ts)] [5] 승격 완료" \
  || echo "[$(ts)] [5] 승격 실패 (계속)"

# 6) 최종 PG 동기화 (시드 갱신 + 그래프 승격분 반영)
echo "[$(ts)] [6] 최종 PG 동기화 중..."
"$PYTHON" -m veristar.db.migrate \
  --seed  "$SEED" \
  --vault "$VAULT" \
  --embed \
  && echo "[$(ts)] [6] 최종 PG 동기화 완료" \
  || echo "[$(ts)] [6] 최종 PG 동기화 실패 (계속)"

# 7) 서버가 실행 중이면 핫 리로드 신호
if [ -f "$ROOT/.run/server.pid" ] && kill -0 "$(cat "$ROOT/.run/server.pid")" 2>/dev/null; then
  echo "[$(ts)] [7] 서버 재시작..."
  bash "$ROOT/scripts/server.sh" restart
fi

echo "[$(ts)] ====== 수집 완료 ======"
