import sys
import os

# Insert blog-hub root onto sys.path so `backend.*` resolves regardless of how
# pytest was invoked or what CWD is.
_blog_hub_root = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))  # blog-hub/
sys.path.insert(0, _blog_hub_root)

import pytest
from fastapi.testclient import TestClient
from backend.main import app
import backend.store as store


@pytest.fixture(autouse=True)
def reset_store():
    """Reset in-memory store before every test."""
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    return TestClient(app)
