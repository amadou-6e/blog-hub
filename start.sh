#!/usr/bin/env bash
# start.sh — start BlogHub backend on a free port and bring up the cli-runner.
#
# Usage:
#   ./start.sh            # auto-picks a free port
#   ./start.sh 8080       # use a specific port
#
# The backend URL is printed at startup so you can open it in a browser.
# Press Ctrl+C to stop everything.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Pick a port ───────────────────────────────────────────────────────────────
if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
  PORT="$1"
else
  # Find a free TCP port
  PORT=$(python3 -c "
import socket
s = socket.socket()
s.bind(('127.0.0.1', 0))
print(s.getsockname()[1])
s.close()
")
fi

# ── Start cli-runner ──────────────────────────────────────────────────────────
echo "Starting cli-runner..."
docker compose up -d cli-runner

# Wait up to 15 s for it to be healthy
for i in $(seq 1 30); do
  if curl -sf http://localhost:8001/health >/dev/null 2>&1; then
    echo "cli-runner ready on :8001"
    break
  fi
  sleep 0.5
  if [[ $i -eq 30 ]]; then
    echo "WARNING: cli-runner did not become healthy within 15 s — continuing anyway"
  fi
done

# ── Start backend ─────────────────────────────────────────────────────────────
echo ""
echo "Starting backend on http://127.0.0.1:${PORT}"
echo "Open: http://127.0.0.1:${PORT}/screens/overview/v3.html"
echo ""
echo "Press Ctrl+C to stop."
echo ""

# Activate venv if present
if [[ -f ".venv/Scripts/activate" ]]; then
  # Windows venv via Git Bash
  source .venv/Scripts/activate
elif [[ -f ".venv/bin/activate" ]]; then
  source .venv/bin/activate
fi

# Trap Ctrl+C to also stop docker
cleanup() {
  echo ""
  echo "Stopping cli-runner..."
  docker compose stop cli-runner 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

python -m uvicorn backend.main:app \
  --host 127.0.0.1 \
  --port "$PORT" \
  --reload
