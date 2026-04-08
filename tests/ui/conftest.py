"""
Shared fixtures for Playwright UI tests.

Requires a live backend on http://localhost:8000.
Start it with:
    uvicorn backend.main:app --port 8000
then run:
    pytest tests/ui -m browser
"""
import pytest
import requests


BASE_URL = "http://localhost:8000"
RUNNER_URL = "http://localhost:8001"
SETTINGS_URL = f"{BASE_URL}/screens/settings/v2.html"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "browser: Playwright browser tests that require a live server on port 8000"
    )


@pytest.fixture(autouse=True)
def reset_store():
    """Reset in-memory store to seed state before each test."""
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
    page.goto(SETTINGS_URL)
    return page


@pytest.fixture
def ai_providers_page(settings_page):
    """Open the AI Providers tab and return the page."""
    settings_page.get_by_role("button", name="AI Providers").click()
    settings_page.wait_for_selector("#ai-wrap-anthropic", timeout=5000)
    return settings_page
