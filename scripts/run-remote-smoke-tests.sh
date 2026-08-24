#!/usr/bin/env bash
set -euo pipefail

platform="${1:-all}"
shift || true

hashnode_test="tests/tests_backend/test_connections_drafts.py::TestDraftsIntegration::test_integration_hashnode_list"
devto_test="tests/tests_backend/test_connections_drafts.py::TestDraftsIntegration::test_integration_devto_list"

tests=()

add_hashnode_test() {
  if [[ -n "${HASHNODE_PAT:-}" ]]; then
    tests+=("$hashnode_test")
  else
    echo "Skipping Hashnode smoke test: HASHNODE_PAT is not set"
  fi
}

add_devto_test() {
  if [[ -n "${DEVTO_API_KEY:-}" ]]; then
    tests+=("$devto_test")
  else
    echo "Skipping Dev.to smoke test: DEVTO_API_KEY is not set"
  fi
}

case "$platform" in
  all)
    add_hashnode_test
    add_devto_test
    ;;
  hashnode)
    add_hashnode_test
    ;;
  devto)
    add_devto_test
    ;;
  *)
    echo "Unsupported platform: $platform" >&2
    exit 2
    ;;
esac

if [[ ${#tests[@]} -eq 0 ]]; then
  exit 0
fi

python -m pytest --strict-markers -m integration "${tests[@]}" "$@"
