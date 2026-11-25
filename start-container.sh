#!/usr/bin/env bash
set -euo pipefail
export ORBIT_ENABLE_GPU_JOBS=0
python -m uvicorn orbit_backend.api:app_factory --factory --host 127.0.0.1 --port 8000 &
api=$!
python -m orbit_backend.worker --role cpu &
worker=$!
node orbit/node_modules/next/dist/bin/next start orbit --hostname :: --port 3000 &
frontend=$!
cleanup() {
  kill "$api" "$worker" "$frontend" 2>/dev/null || true
  wait "$api" "$worker" "$frontend" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
wait -n "$api" "$worker" "$frontend"
