#!/usr/bin/env bash
# Remove the app password if you forget it (your data is not encrypted with it, so nothing is lost).
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=backend exec .venv/bin/python -m app.auth reset
