#!/usr/bin/env bash
set -euo pipefail

browser="${BLOGHUB_TEST_BROWSER:-chromium}"

python -m pytest \
  --strict-markers \
  -m browser \
  tests/tests_ui/bridges/test_overview_import_bridge.py \
  tests/tests_ui/screens/test_editor.py \
  tests/tests_ui/screens/test_overview_card.py \
  --browser "$browser" \
  "$@"
