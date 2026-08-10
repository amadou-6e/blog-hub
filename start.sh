#!/usr/bin/env bash
# Start the complete BlogHub development stack through the shared Python launcher.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f ".venv/Scripts/activate" ]]; then
  source .venv/Scripts/activate
elif [[ -f ".venv/bin/activate" ]]; then
  source .venv/bin/activate
fi

if command -v python >/dev/null 2>&1; then
  PYTHON=python
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  echo "BlogHub startup failed: Python is not available" >&2
  exit 1
fi

ARGS=("$@")
if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
  ARGS=(--port "$1" "${@:2}")
fi

exec "$PYTHON" start.py "${ARGS[@]}"
