from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event

import pytest

from backend.store.backends.sqlite import SQLiteStore


@pytest.fixture(params=["file", "memory"])
def browser_store(tmp_path, request):
    database = ":memory:" if request.param == "memory" else str(tmp_path / "bloghub.db")
    store = SQLiteStore(database, str(tmp_path / "blobs"))
    store.start_browser_connection(
        store.SEED_USER_ID,
        "medium",
        session_id="session-test",
        organization_id="org-test",
        profile_id="profile-test",
        app_url="http://localhost/session-test",
    )
    store.update_browser_connection(store.SEED_USER_ID, "medium", "connected")
    try:
        yield store
    finally:
        store.close()


@pytest.mark.parametrize("method", ["get_browser_connection", "get_reusable_browser_profile"])
def test_browser_read_waits_for_workspace_writer(browser_store, method):
    store = browser_store
    started = Event()

    def read():
        started.set()
        return getattr(store, method)(store.SEED_USER_ID, "medium")

    with ThreadPoolExecutor(max_workers=1) as executor:
        with store._workspace_lock.acquire():
            future = executor.submit(read)
            assert started.wait(timeout=5)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
            store.disconnect_browser_connection(store.SEED_USER_ID, "medium")
        result = future.result(timeout=5)
    if method == "get_browser_connection":
        assert result["status"] == "disconnected"
    else:
        assert result["profile_id"] == "profile-test"


@pytest.mark.parametrize("method", ["get_browser_connection", "get_reusable_browser_profile"])
def test_parallel_browser_reads_preserve_results(browser_store, method):
    store = browser_store
    read = getattr(store, method)
    expected = read(store.SEED_USER_ID, "medium")
    start = Barrier(8)

    def poll():
        start.wait(timeout=5)
        for _ in range(500):
            assert read(store.SEED_USER_ID, "medium") == expected
            assert read("missing-user", "medium") is None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(poll) for _ in range(8)]
        for future in futures:
            future.result(timeout=30)
