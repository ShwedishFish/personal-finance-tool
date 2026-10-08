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

exec .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$PORT" --reload --reload-dir backend
