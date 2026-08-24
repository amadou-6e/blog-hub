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
from backend.workers.handlers import HANDLERS
from backend.workers.worker import DurableWorker


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


@pytest.fixture
def run_jobs():
    """Drain durable jobs explicitly; API requests never execute jobs inline."""
    def run(*, force_retries: bool = False) -> int:
        worker = DurableWorker(
            store._backend,
            HANDLERS,
            worker_id="pytest-worker",
            queues=("default", "agents", "publishing"),
            lease_seconds=30,
        )
        completed = 0
        while worker.run_once():
            completed += 1
            if force_retries:
                store._backend._con.execute(
                    "UPDATE jobs SET available_at=created_at WHERE status='waiting' "
                    "AND available_at IS NOT NULL"
                )
                store._backend._con.commit()
        return completed
    return run
