import sys
import os

_blog_hub_root = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, _blog_hub_root)

os.environ.setdefault("BLOGHUB_DB_PATH", ":memory:")

import pytest
from fastapi.testclient import TestClient
from backend.main import app
import backend.store as store


@pytest.fixture(autouse=True)
def reset_store():
    store.reset()
    yield
    store.reset()


@pytest.fixture
def anon_client():
    """Unauthenticated TestClient — use only for tests that need to verify 401 responses."""
    return TestClient(app)


@pytest.fixture
def client(anon_client):
    """TestClient pre-authenticated as the seed user (owns the seed articles)."""
    anon_client.post("/api/auth/login",
                     json={"email": "seed@example.com", "password": "seed1234",
                           "remember_me": False})
    return anon_client


@pytest.fixture
def auth_client(client):
    """Alias for client — kept for backward compatibility."""
    return client
