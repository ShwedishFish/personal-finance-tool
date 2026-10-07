#!/usr/bin/env bash
# Start the local dev server at http://127.0.0.1:8020 (creates .venv on first run).
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PFT_PORT:-8020}"

if [ ! -x .venv/bin/python ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 .venv
  else
    python3 -m venv .venv
  fi
fi

if command -v uv >/dev/null 2>&1; then
  uv pip install --quiet --python .venv/bin/python -r requirements-dev.txt
else
  .venv/bin/python -m pip install --quiet -r requirements-dev.txt
fi

exec .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$PORT" --reload
