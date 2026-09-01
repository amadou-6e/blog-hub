from backend.store.locking import WorkspaceLock


def test_workspace_lock_is_reentrant_within_a_thread(tmp_path):
    lock = WorkspaceLock(tmp_path / "workspace.lock")
    nested = False

    with lock.acquire():
        with lock.acquire():
            nested = True

    assert nested
