#!/usr/bin/env bash
set -euo pipefail

browser="${BLOGHUB_TEST_BROWSER:-chromium}"

python -m pytest \
  --strict-markers \
  -m browser \
  tests/tests_ui \
  --browser "$browser" \
  "$@"
