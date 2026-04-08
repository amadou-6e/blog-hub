"""Dev-only router — reset in-memory store between test runs."""
from fastapi import APIRouter
import backend.store as store
import backend.services.cli_runner as runner

router = APIRouter(prefix="/api/dev", tags=["dev"])


@router.post("/reset")
def dev_reset():
    """Reset store to seed state. Used by Playwright beforeEach.

    After resetting, re-checks whether the CLI providers (Claude, OpenAI) are
    still authenticated in the cli-runner and restores their connection records
    so tests and manual use don't need to re-login after every reset.
    """
    store.reset()
    for conn_id in ("anthropic", "openai"):
        try:
            result = runner.login_status(conn_id)
            if result.get("status") == "connected":
                store.save_connection(
                    conn_id,
                    token="cli_session",
                    status="connected",
                    username=result.get("username"),
                )
        except Exception:
            pass  # runner not available — leave disconnected
    return {"status": "reset"}
