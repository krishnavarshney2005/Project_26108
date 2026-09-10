#!/usr/bin/env bash
# start.sh — Combined Render Free service launcher.
#
# Starts both processes in one Render Free container:
#   1. AI Engine (localhost:10000, analyze-only, no Recommender)
#   2. Backend   ($PORT, public-facing)
#
# IMPORTANT: uses `python -m uvicorn`, not .venv/bin/uvicorn.
# The .venv directories are gitignored and absent on Render.
# Render's build command (pip install -r ... -r ...) installs
# everything into the system Python on PATH.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
AI_PORT=10001
HEALTH_URL="http://127.0.0.1:${AI_PORT}/health"

echo "[start.sh] Repo root: ${REPO_ROOT}"
echo "[start.sh] Starting AI Engine on localhost:${AI_PORT} (SKIP_RECOMMENDER=true)..."

SKIP_RECOMMENDER=true \
AI_MODE=ml \
PYTHONPATH="${REPO_ROOT}/ai-engine" \
  python3 -m uvicorn api.main:app \
    --app-dir "${REPO_ROOT}/ai-engine" \
    --host 127.0.0.1 \
    --port "${AI_PORT}" \
    --workers 1 \
    --log-level info &

AI_PID=$!
echo "[start.sh] AI Engine PID: ${AI_PID}"

# Wait up to 90 seconds for the AI engine /health to return status=ok.
echo "[start.sh] Waiting for AI Engine to become ready..."
READY=0
for i in $(seq 1 90); do
  STATUS=$(curl -sf "${HEALTH_URL}" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || true)
  if [ "${STATUS}" = "ok" ]; then
    READY=1
    echo "[start.sh] AI Engine ready after ${i}s (status=ok)."
    break
  fi
  sleep 1
done

if [ "${READY}" -eq 0 ]; then
  echo "[start.sh] ERROR: AI Engine did not become ready within 90s. Aborting."
  kill "${AI_PID}" 2>/dev/null || true
  exit 1
fi

echo "[start.sh] Starting Backend on 0.0.0.0:${PORT}..."

AIML_SERVICE_URL="http://127.0.0.1:${AI_PORT}/analyze" \
SEMANTIC_RETRIEVAL_ENABLED=false \
PYTHONPATH="${REPO_ROOT}/backend" \
  python3 -m uvicorn kartikey.api.main:app \
    --app-dir "${REPO_ROOT}/backend" \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --workers 1 \
    --log-level info

# If the backend exits (crash or Ctrl-C), kill the AI engine too.
kill "${AI_PID}" 2>/dev/null || true
