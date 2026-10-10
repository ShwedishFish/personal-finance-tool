#!/usr/bin/env bash
# Double-click to start the app and open it in your browser. Close this window to stop it.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PFT_PORT:-8020}"
URL="http://127.0.0.1:$PORT/"

./scripts/dev.sh --setup-only
if curl -fsS "${URL}api/health" >/dev/null 2>&1; then
  open "$URL"
  exit 0
fi

(
  for _ in $(seq 60); do
    curl -fsS "${URL}api/health" >/dev/null 2>&1 && { open "$URL"; exit 0; }
    sleep 0.5
  done
) &
echo "Personal Finance Tool is running at $URL. Your data stays on this computer."
echo "Close this window to stop it."
exec ./scripts/dev.sh --no-reload
