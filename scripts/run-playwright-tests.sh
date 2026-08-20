#!/usr/bin/env bash
set -euo pipefail

if [ -z "${BLOGHUB_PLAYWRIGHT_PYTHON_COMMAND:-}" ] && [ -z "${PYTHON:-}" ]; then
  if command -v uv >/dev/null 2>&1; then
    export BLOGHUB_PLAYWRIGHT_PYTHON_COMMAND="uv run --with-requirements requirements.txt --with-requirements backend/requirements.txt python"
  fi
fi

if [ -z "${BLOGHUB_PLAYWRIGHT_PYTHON_COMMAND:-}" ] && [ -z "${PYTHON:-}" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import uvicorn" >/dev/null 2>&1; then
      export PYTHON="$candidate"
      break
    fi
  done
fi

npx playwright test --grep-invert "@live" "$@"
