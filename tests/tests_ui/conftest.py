"""
Shared fixtures for Playwright UI tests.

The server is started automatically on a free port before test collection.
Set BLOGHUB_TEST_URL to skip spawning and point at a running instance instead.
"""
import os
import socket
import threading
import time

import pytest
import requests
import uvicorn

# Populated in pytest_configure (before test modules are imported/collected).
BASE_URL = os.environ.get("BLOGHUB_TEST_URL", "")
SETTINGS_URL = f"{BASE_URL}/screens/settings/v2.html"  # updated in pytest_configure
RUNNER_URL = "http://localhost:8001"

_server_thread: "threading.Thread | None" = None

# ── server helpers ────────────────────────────────────────────────────────────


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _UvicornThread(threading.Thread):

    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.port = port
        self._server: uvicorn.Server | None = None

    def run(self):
        cfg = uvicorn.Config(
            "backend.main:app",
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(cfg)
        self._server.run()

    def stop(self):
        if self._server:
            self._server.should_exit = True


# ── pytest hooks ─────────────────────────────────────────────────────────────


def pytest_configure(config):
    """Start the server before test collection so imported BASE_URL is correct."""
    global BASE_URL, SETTINGS_URL, _server_thread

    config.addinivalue_line(
        "markers",
        "browser: Playwright browser tests (server started automatically)",
    )

    if BASE_URL:  # BLOGHUB_TEST_URL was set — don't spawn
        SETTINGS_URL = f"{BASE_URL}/screens/settings/v2.html"
        return

    port = _find_free_port()
    _server_thread = _UvicornThread(port)
    _server_thread.start()
    BASE_URL = f"http://127.0.0.1:{port}"
    SETTINGS_URL = f"{BASE_URL}/screens/settings/v2.html"

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{BASE_URL}/health", timeout=1).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.1)
    else:
        raise RuntimeError(f"Test server on port {port} did not become ready within 15 s")


def pytest_sessionfinish(session, exitstatus):
    """Stop the spawned server after all tests have run."""
    global _server_thread
    if _server_thread is not None:
        _server_thread.stop()
        _server_thread.join(timeout=5)
        _server_thread = None


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_store():
    """Reset in-memory store to seed state before/after each test."""
    requests.post(f"{BASE_URL}/api/dev/reset")
    yield
    requests.post(f"{BASE_URL}/api/dev/reset")


@pytest.fixture
def requests_session():
    """A requests.Session pre-pointed at the live backend."""
    return requests.Session()


@pytest.fixture
def settings_page(page):
    """Navigate to the settings screen and return the page."""
    response = page.request.post(
        f"{BASE_URL}/api/auth/login",
        data={
            "email": "seed@example.com",
            "password": "seed1234",
            "remember_me": False,
        },
    )
    assert response.ok
    page.goto(f"{BASE_URL}/screens/settings/v2.html")
    return page


@pytest.fixture
def ai_providers_page(settings_page):
    """Open the AI Providers tab and return the page."""
    settings_page.get_by_role("button", name="AI Providers").click()
    settings_page.wait_for_selector("#ai-wrap-anthropic", timeout=5000)
    return settings_page
