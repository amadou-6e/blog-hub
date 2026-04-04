"""Dev-only router — reset in-memory store between test runs."""
from fastapi import APIRouter
import backend.store.memory as store

router = APIRouter(prefix="/api/dev", tags=["dev"])


@router.post("/reset")
def dev_reset():
    """Reset store to seed state. Used by Playwright beforeEach."""
    store.reset()
    return {"status": "reset"}
