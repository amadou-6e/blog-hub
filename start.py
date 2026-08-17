"""
BlogHub dev launcher.
Finds the first free port starting at 8082 and starts uvicorn there.
Pass any extra uvicorn flags as arguments, e.g.:  python start.py --reload
"""
import socket
import subprocess
import sys
from pathlib import Path


def find_free_port(start: int = 8082, end: int = 8090) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start}-{end}")


port = find_free_port()
print(f"\n  BlogHub: http://localhost:{port}/screens/overview/v3.html\n")
root = Path(__file__).resolve().parent
worker = subprocess.Popen([sys.executable, str(root / "scripts" / "bloghub_worker.py")])
try:
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port),
         *sys.argv[1:]]
    )
finally:
    worker.terminate()
    try:
        worker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        worker.kill()
