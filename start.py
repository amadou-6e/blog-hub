"""
BlogHub dev server launcher.

Usage:
  python start.py              # auto-finds a free port in 8082-8099
  python start.py --port 9000  # pin to a specific port (exits if already taken)
  python start.py --reload     # extra uvicorn flags are forwarded

PORT SELECTION
  Scans 8082-8099 in order.  If a port is occupied you'll see:
    ⚠  Port 8082 taken — trying 8083 ...
  The first free port is used and its URL printed prominently.

STOP THE SERVER
  python stop.py               # kills all BlogHub uvicorn processes
  Ctrl+C in this terminal      # also works

A PID record is written to .dev-server.pid so stop.py can find the process.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import os
import socket
import subprocess
import sys

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PID_FILE   = os.path.join(BASE_DIR, ".dev-server.pid")
PORT_RANGE = range(8082, 8100)


# ─── helpers ────────────────────────────────────────────────────

def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _find_port(pinned: int | None) -> int:
    if pinned is not None:
        if not _port_free(pinned):
            print(f"\n  ✗  Port {pinned} is already taken.")
            print(f"     Run:  python stop.py   to kill existing BlogHub servers.")
            print(f"     Or omit --port to auto-select a free port.\n")
            sys.exit(1)
        return pinned

    for port in PORT_RANGE:
        if _port_free(port):
            return port
        print(f"  ⚠  Port {port} taken — trying {port + 1} ...")

    print(f"\n  ✗  No free port in {PORT_RANGE.start}–{PORT_RANGE.stop - 1}.")
    print(f"     Run:  python stop.py   to kill existing BlogHub servers.\n")
    sys.exit(1)


def _banner(port: int) -> None:
    w = 55
    sep = "─" * w
    print(f"\n  ┌{sep}┐")
    print(f"  │  BlogHub dev server{' ' * (w - 20)}│")
    print(f"  │{' ' * w}│")
    print(f"  │  Overview  → http://localhost:{port}/screens/overview/v3.html")
    print(f"  │  Create    → http://localhost:{port}/screens/create-article/v1.html")
    print(f"  │  Import    → http://localhost:{port}/screens/import-article/v1.html")
    print(f"  │  Settings  → http://localhost:{port}/screens/settings/v2.html")
    print(f"  │  API docs  → http://localhost:{port}/docs")
    print(f"  │{' ' * w}│")
    print(f"  │  Stop: python stop.py   or   Ctrl+C{' ' * (w - 36)}│")
    print(f"  └{sep}┘\n")


def _write_pid(pid: int, port: int) -> None:
    with open(PID_FILE, "w") as fh:
        fh.write(f"{pid}\n{port}\n")


def _remove_pid() -> None:
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)


# ─── main ───────────────────────────────────────────────────────

def main() -> None:
    # Split our --port flag from flags we'll forward to uvicorn
    args = list(sys.argv[1:])
    pinned: int | None = None
    if "--port" in args:
        idx = args.index("--port")
        pinned = int(args[idx + 1])
        args = args[:idx] + args[idx + 2:]

    port = _find_port(pinned)
    _banner(port)

    cmd = [sys.executable, "-m", "uvicorn", "backend.main:app",
           "--port", str(port), "--reload", *args]

    proc = subprocess.Popen(cmd, cwd=BASE_DIR)
    _write_pid(proc.pid, port)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
    finally:
        _remove_pid()


if __name__ == "__main__":
    main()
