#!/usr/bin/env bash
set -euo pipefail

python -m pytest --strict-markers -m "not integration and not browser" "$@"
