#!/usr/bin/env bash
# Boot the whole app. Usage:
#   ./run.sh           start the server (uses the existing web build)
#   ./run.sh --build   rebuild the React HUD first, then start
set -e
cd "$(dirname "$0")"

source .venv/bin/activate

if [ "$1" = "--build" ]; then
  echo "▸ building web HUD…"
  (cd web && npm run build)
fi

# kill any stale server holding the port
lsof -ti tcp:8000 | xargs kill -9 2>/dev/null || true

echo "▸ open http://localhost:8000"
python server.py
