"""Orchestrate an approved browser publish without exposing browser credentials."""
from __future__ import annotations

import re

import backend.services.cli_runner as runner
import backend.store as store
from blogs.medium.render import render_clipboard_html


def _medium_article_fragment(rendered_html: str) -> str:
    match = re.search(
        r"<article[^>]*>([\s\S]*?)</article>", rendered_html,
        flags=re.IGNORECASE,
    )
    fragment = match.group(1) if match else rendered_html
    return re.sub(
        r"^\s*<h1[^>]*>[\s\S]*?</h1>\s*", "", fragment,
        count=1, flags=re.IGNORECASE,
    )


def execute_hashnode_run(*, user_id: str, run_id: str) -> None:
    run = store.get_browser_publish_run(user_id, run_id)
    if run is None or run["status"] != "running":
        return
    revision = store.get_article_revision(
        user_id, run["article_id"], run["article_revision_id"]
    )
    if revision is None:
        store.complete_browser_publish_run(user_id, run_id, error="Article revision not found")
        return
    browser_connection = store.get_browser_connection(user_id, "hashnode")
    if not browser_connection or browser_connection["status"] != "connected":
        store.complete_browser_publish_run(
            user_id, run_id, error="Hashnode browser login required"
        )
        return
    try:
        result = runner.hashnode_browser_upload(
            organization_id=browser_connection["skyvern_organization_id"],
            profile_id=browser_connection["skyvern_profile_id"],
            title=revision["title"], article_md=revision["content"],
            publish=run["mode"] == "publish",
        )
        if not result.get("success"):
            error = result.get("error") or "Hashnode upload failed"
            store.apply_push_result(
                user_id, run["article_id"], "hashnode", success=False,
                error=error, label="Browser upload failed",
            )
            store.complete_browser_publish_run(
                user_id, run_id, result=result, error=error
            )
            return
        store.apply_push_result(
            user_id, run["article_id"], "hashnode", success=True,
            url=result.get("url"), draft_id=result.get("draft_id"),
            label="Published" if run["mode"] == "publish" else "Draft",
            status="published" if run["mode"] == "publish" else "draft",
        )
        store.complete_browser_publish_run(user_id, run_id, result=result)
    except Exception as exc:
        store.apply_push_result(
            user_id, run["article_id"], "hashnode", success=False,
            error=str(exc)[:500], label="Browser upload failed",
        )
        store.complete_browser_publish_run(user_id, run_id, error=str(exc)[:500])


def execute_medium_run(*, user_id: str, run_id: str) -> None:
    run = store.get_browser_publish_run(user_id, run_id)
    if run is None or run["status"] != "running":
        return
    revision = store.get_article_revision(
        user_id, run["article_id"], run["article_revision_id"]
    )
    if revision is None:
        store.complete_browser_publish_run(user_id, run_id, error="Article revision not found")
        return
    browser_connection = store.get_browser_connection(user_id, "medium")
    if not browser_connection or browser_connection["status"] != "connected":
        store.complete_browser_publish_run(
            user_id, run_id, error="Medium browser login required"
        )
        return
    try:
        rendered = render_clipboard_html(revision["content"])
        article_html = _medium_article_fragment(rendered.html)
        result = runner.medium_browser_upload(
            organization_id=browser_connection["skyvern_organization_id"],
            profile_id=browser_connection["skyvern_profile_id"],
            title=revision["title"], article_html=article_html,
            publish=run["mode"] == "publish",
        )
        if not result.get("success"):
            error = result.get("error") or "Medium upload failed"
            store.apply_push_result(
                user_id, run["article_id"], "medium", success=False,
                error=error, label="Browser upload failed",
            )
            store.complete_browser_publish_run(
                user_id, run_id, result=result, error=error
            )
            return
        store.apply_push_result(
            user_id, run["article_id"], "medium", success=True,
            url=result.get("url"), draft_id=result.get("draft_id"),
            label="Published" if run["mode"] == "publish" else "Draft",
            status="published" if run["mode"] == "publish" else "draft",
        )
        store.complete_browser_publish_run(user_id, run_id, result=result)
    except Exception as exc:
        store.apply_push_result(
            user_id, run["article_id"], "medium", success=False,
            error=str(exc)[:500], label="Browser upload failed",
        )
        store.complete_browser_publish_run(user_id, run_id, error=str(exc)[:500])


EXECUTORS = {
    "hashnode": execute_hashnode_run,
    "medium": execute_medium_run,
}
