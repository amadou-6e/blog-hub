"""
BlogHub dev server teardown.

Usage:
  python stop.py        # kills all BlogHub uvicorn processes and cleans up

How it finds processes (two complementary strategies):
  1. Reads .dev-server.pid written by start.py
  2. Scans all processes via psutil for any uvicorn running backend.main:app
     from this project directory — catches servers started manually too
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(BASE_DIR, ".dev-server.pid")


def _try_import_psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        print("  psutil not installed — run:  pip install psutil")
        sys.exit(1)


def _kill(proc, label: str) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=5)
        print(f"  ✓  Stopped {label} (PID {proc.pid})")
    except Exception as exc:
        try:
            proc.kill()
            print(f"  ✓  Force-killed {label} (PID {proc.pid})")
        except Exception:
            print(f"  ✗  Could not stop {label} (PID {proc.pid}): {exc}")


def main() -> None:
    psutil = _try_import_psutil()

    killed_pids: set[int] = set()

    # ── Strategy 1: PID file from start.py ──────────────────────
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as fh:
                lines = fh.read().splitlines()
            pid  = int(lines[0])
            port = lines[1] if len(lines) > 1 else "?"
            print(f"  Found .dev-server.pid → PID {pid} (port {port})")
            try:
                proc = psutil.Process(pid)
                _kill(proc, f"server (port {port})")
                killed_pids.add(pid)
            except psutil.NoSuchProcess:
                print(f"  PID {pid} is no longer running (already stopped?)")
        except Exception as exc:
            print(f"  Could not read .dev-server.pid: {exc}")
        finally:
            os.remove(PID_FILE)

    # ── Strategy 2: scan all processes for uvicorn + backend.main ─
    for proc in psutil.process_iter(["pid", "cmdline", "cwd"]):
        try:
            if proc.pid in killed_pids:
                continue
            cmdline = proc.cmdline()
            cwd     = proc.cwd()
            if not cmdline:
                continue
            cmd_str = " ".join(cmdline)
            is_uvicorn   = "uvicorn" in cmd_str
            is_our_app   = "backend.main:app" in cmd_str or "backend.main" in cmd_str
            is_our_dir   = os.path.normcase(cwd) == os.path.normcase(BASE_DIR)
            if is_uvicorn and (is_our_app or is_our_dir):
                _kill(proc, "uvicorn")
                killed_pids.add(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not killed_pids:
        print("  No running BlogHub servers found.")
    else:
        print(f"\n  Done. {len(killed_pids)} process(es) stopped.")


if __name__ == "__main__":
    main()
