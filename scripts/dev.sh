#!/usr/bin/env bash
# Start the local dev server at http://127.0.0.1:8020 (creates .venv on first run).
#   --no-reload   serve without watching for code changes (used by scripts/launch-agent.sh)
#   --setup-only  create .venv and install requirements, then exit
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PFT_PORT:-8020}"
MODE="${1:-}"

if [ ! -x .venv/bin/python ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 .venv
  else
    python3 -m venv .venv
  fi
fi

# Reinstall only when the requirements change; fall back to pip if uv is missing or broken.
stamp=.venv/.installed-requirements
want="$(cat requirements.txt requirements-dev.txt)"
if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$want" ]; then
  if ! { command -v uv >/dev/null 2>&1 && uv pip install --quiet --python .venv/bin/python -r requirements-dev.txt; }; then
    .venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1 || true
    .venv/bin/python -m pip install --quiet -r requirements-dev.txt
  fi
  printf '%s' "$want" > "$stamp"
fi

[ "$MODE" = "--setup-only" ] && exit 0

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  if [ -z "$MODE" ] && curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    # The editor task waits for "Application startup complete" before opening the browser.
    echo "The app is already running at http://127.0.0.1:$PORT/ (always-on launcher?). Application startup complete."
    exit 0
  fi
  echo "Port $PORT is already in use; set PFT_PORT to use another." >&2
  exit 1
fi

if [ "$MODE" = "--no-reload" ]; then
  exec .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$PORT"
fi
exec .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$PORT" --reload --reload-dir backend
