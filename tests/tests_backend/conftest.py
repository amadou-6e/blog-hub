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
def client():
    return TestClient(app)


@pytest.fixture
def auth_client(client):
    """TestClient with a registered and logged-in user session."""
    client.post("/api/auth/register",
                json={"email": "test@example.com", "password": "password123"})
    return client
