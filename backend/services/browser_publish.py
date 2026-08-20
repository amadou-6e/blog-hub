"""Orchestrate an approved browser publish without exposing browser credentials."""
from __future__ import annotations

import backend.services.cli_runner as runner
import backend.store as store
from backend.security import redact_secrets


def _safe_error(value: object, fallback: str) -> str:
    return redact_secrets(value or fallback)[:500]


def execute_run(*, user_id: str, run_id: str) -> None:
    run = store.get_browser_publish_run(user_id, run_id)
    if run is None or run["status"] != "running":
        return
    revision = store.get_article_revision(
        user_id, run["article_id"], run["article_revision_id"]
    )
    if revision is None:
        store.complete_browser_publish_run(user_id, run_id, error="Article revision not found")
        return
    platform = run["platform"]
    browser_connection = store.get_browser_connection(user_id, platform)
    if not browser_connection or browser_connection["status"] != "connected":
        store.complete_browser_publish_run(
            user_id, run_id, error=f"{platform.title()} browser login required"
        )
        return
    try:
        operation = "publish" if run["mode"] == "publish" else "create_draft"
        result = runner.browser_operation(
            platform,
            operation,
            organization_id=browser_connection["skyvern_organization_id"],
            profile_id=browser_connection["skyvern_profile_id"],
            article={"title": revision["title"], "body": revision["content"]},
            approved=True,
        )
        if not result.get("success"):
            error = _safe_error(
                result.get("error"), f"{platform.title()} upload failed"
            )
            result = {**result, "error": error}
            store.apply_push_result(
                user_id, run["article_id"], platform, success=False,
                error=error, label="Browser upload failed",
            )
            store.complete_browser_publish_run(
                user_id, run_id, result=result, error=error
            )
            return
        store.apply_push_result(
            user_id, run["article_id"], platform, success=True,
            url=result.get("url"), draft_id=result.get("draft_id"),
            label="Published" if run["mode"] == "publish" else "Draft",
            status="published" if run["mode"] == "publish" else "draft",
        )
        store.complete_browser_publish_run(user_id, run_id, result=result)
    except Exception as exc:
        error = _safe_error(exc, f"{platform.title()} upload failed")
        store.apply_push_result(
            user_id, run["article_id"], platform, success=False,
            error=error, label="Browser upload failed",
        )
        store.complete_browser_publish_run(user_id, run_id, error=error)


def execute_hashnode_run(*, user_id: str, run_id: str) -> None:
    """Compatibility alias for callers created before extension dispatch."""
    execute_run(user_id=user_id, run_id=run_id)
