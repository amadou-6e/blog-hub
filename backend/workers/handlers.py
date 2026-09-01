"""Built-in durable job handlers."""
from __future__ import annotations

import re
from dataclasses import asdict

import backend.services.cli_runner as runner
import backend.services.agent_chat as agent_chat
import backend.services.browser_publish as browser_publish
import backend.services.connection_health as connection_health
from backend.services.agent_service import (
    GenerationError,
    generate_markdown,
    persist_generation,
)
from backend.services.push import push_article_to_platforms
from backend.services.hashnode_sync import (
    RemoteSyncArticle,
    _fingerprint,
    sync_hashnode_articles,
    sync_hashnode_browser_records,
)
from backend.services.medium_sync import sync_medium_browser_records
from backend.workers.worker import (
    JobContext,
    PermanentJobError,
    RetryableJobError,
)


def handle_generate(context: JobContext, payload: dict) -> dict:
    required = ("article_id", "brief", "skill", "provider", "word_count")
    if any(key not in payload for key in required):
        raise PermanentJobError("Generate job payload is incomplete")
    try:
        generated = context.run_effect(
            "provider-generation",
            lambda: generate_markdown(
                context.store,
                user_id=context.user_id,
                brief=payload["brief"],
                skill=payload["skill"],
                provider=payload["provider"],
                word_count=payload["word_count"],
                context_text=payload.get("context_text"),
            ),
            release_on_error=True,
        )
    except GenerationError as exc:
        raise RetryableJobError(str(exc)) from exc
    context.checkpoint(stage="provider_completed")
    result = persist_generation(
        context.store,
        user_id=context.user_id,
        article_id=payload["article_id"],
        generated_markdown=generated,
        destinations=payload.get("destinations", []),
        session_id=payload.get("session_id"),
    )
    context.checkpoint(stage="persisted")
    return result


def handle_push(context: JobContext, payload: dict) -> dict:
    article_id = payload.get("article_id")
    platforms = payload.get("platforms") or []
    article = context.store.get_article(context.user_id, article_id)
    if article is None:
        raise PermanentJobError(f"Article {article_id} no longer exists")
    completed = set((context.job.get("checkpoint") or {}).get("platforms", []))
    job_result: dict[str, dict] = {}
    for platform in platforms:
        context.check_stopped()

        def publish_one() -> dict:
            outcomes = push_article_to_platforms(
                article, [platform],
                get_connection_token=lambda connection_id: context.store.get_connection_token(
                    context.user_id, connection_id
                ),
            )
            return asdict(outcomes[platform])

        result = context.run_effect(f"publish:{platform}", publish_one)
        if platform in completed:
            job_result[platform] = result
            continue
        context.store.apply_push_result(
            context.user_id,
            article_id,
            platform,
            success=result["success"],
            url=result.get("url"),
            error=result.get("error"),
            label=result.get("label"),
            draft_id=result.get("draft_id"),
        )
        if result["success"] and result.get("draft_id") and platform in {"hashnode", "devto"}:
            revision = context.store.get_current_article_revision(
                context.user_id, article_id
            )
            if revision is not None:
                fingerprint = _fingerprint(RemoteSyncArticle(
                    article_id=result["draft_id"],
                    title=revision["title"],
                    body_markdown=revision["content"],
                    published=result.get("status") == "published",
                ))
                existing = context.store.get_remote_article_identity(
                    context.user_id, platform, result["draft_id"]
                )
                context.store.upsert_remote_article_identity(
                    context.user_id,
                    article_id,
                    platform,
                    result["draft_id"],
                    remote_content_fingerprint=fingerprint,
                    subtitle=(existing or {}).get("subtitle"),
                    cover_asset_id=(existing or {}).get("cover_asset_id"),
                    last_sync_status="succeeded",
                    last_sync_result={
                        "action": "pushed",
                        "remoteStatus": result.get("status"),
                    },
                )
                context.store.record_reconciliation_observation(
                    context.user_id,
                    article_id,
                    platform,
                    result["draft_id"],
                    local_revision_id=revision["id"],
                    baseline_fingerprint=fingerprint,
                    local_fingerprint=fingerprint,
                    remote_fingerprint=fingerprint,
                    availability="available",
                    sync_state="in_sync",
                    remote_title=revision["title"],
                    remote_content=revision["content"],
                    remote_url=result.get("url"),
                    remote_status=result.get("status"),
                )
        completed.add(platform)
        context.checkpoint(platforms=sorted(completed))
        job_result[platform] = result
    return job_result


def handle_inspect(context: JobContext, payload: dict) -> dict:
    article_id = payload.get("article_id")
    article = context.store.get_article(context.user_id, article_id)
    if article is None:
        raise PermanentJobError(f"Article {article_id} no longer exists")
    gate = "pass" if article["word_count"] >= 500 else "warn"
    context.store.apply_inspect_result(context.user_id, article_id, gate)
    context.checkpoint(stage="inspected", gate=gate)
    return {"gate": gate}


def _regeneration_prompt(article: dict, comments: list[dict]) -> str:
    comment_lines = "\n".join(
        f"- [{comment['id']}] {comment['author']}: {comment['text']}"
        for comment in comments
    )
    return (
        "You are an editor reviewing a technical blog article. For each comment below, "
        "produce a concise patch suggestion.\n\nFormat each patch as:\nPATCH_START\n"
        "LABEL: <short label>\nCOMMENT_ID: <comment id>\n"
        "REMOVED: <the existing text to replace>\nADDED: <the replacement text>\n"
        "PATCH_END\n\n"
        f"Article (excerpt, first 2000 chars):\n{article.get('body', '')[:2000]}\n\n"
        f"Comments to address:\n{comment_lines}\n\n"
        "Output only PATCH_START...PATCH_END blocks, nothing else."
    )


def handle_regenerate(context: JobContext, payload: dict) -> dict:
    article_id = payload.get("article_id")
    article = context.store.get_article(context.user_id, article_id)
    if article is None:
        raise PermanentJobError(f"Article {article_id} no longer exists")
    unresolved = [
        comment for comment in context.store.list_comments(context.user_id, article_id)
        if not comment["resolved"]
    ]
    if not unresolved:
        return {"patches_created": 0}
    provider = next(
        (
            candidate for candidate in ("anthropic", "openai")
            if context.store.get_connection_token(context.user_id, candidate)
        ),
        None,
    )
    if provider is None:
        raise PermanentJobError("No AI provider connected")
    prompt = _regeneration_prompt(article, unresolved)

    def ask_provider() -> str:
        api_key = (
            context.store.get_connection_token(context.user_id, provider)
            if provider == "openai" else None
        )
        try:
            result = runner.run_task(
                provider=provider, task="generate", article_md=prompt, api_key=api_key
            )
        except runner.RunnerUnavailable as exc:
            raise RetryableJobError(str(exc)) from exc
        if result.get("exit_code", 1) != 0:
            error = (result.get("stderr") or result.get("stdout") or "unknown error")[:500]
            raise RetryableJobError(f"Regeneration failed: {error}")
        return result.get("stdout", "")

    raw_output = context.run_effect(
        "provider-regeneration", ask_provider, release_on_error=True
    )
    blocks = re.findall(r"PATCH_START\s*(.*?)\s*PATCH_END", raw_output, re.DOTALL)
    context.store.delete_patches(context.user_id, article_id)
    patches_created = 0
    for block in blocks:
        fields: dict[str, str] = {}
        for field in ("LABEL", "COMMENT_ID", "REMOVED", "ADDED"):
            match = re.search(
                rf"{field}:\s*(.+?)(?=\n(?:LABEL|COMMENT_ID|REMOVED|ADDED|$))",
                block,
                re.DOTALL,
            )
            if match:
                fields[field] = match.group(1).strip()
        if "REMOVED" in fields and "ADDED" in fields:
            context.store.add_patch(
                context.user_id,
                article_id=article_id,
                label=fields.get("LABEL", "Suggested edit"),
                removed=fields["REMOVED"],
                added=fields["ADDED"],
                comment_id=fields.get("COMMENT_ID") or None,
            )
            patches_created += 1
    context.checkpoint(stage="patches_persisted", patches_created=patches_created)
    return {"patches_created": patches_created}


def handle_sync(context: JobContext, payload: dict) -> dict:
    platform = payload.get("platform")
    if platform not in {"hashnode", "medium"}:
        raise PermanentJobError("Sync job has an unsupported platform")
    browser_connection = context.store.get_browser_connection(
        context.user_id, platform
    )
    health = context.store.get_connection_health(context.user_id, platform)
    if health and health["status"] == "reauthentication_required":
        raise PermanentJobError(
            f"{platform.title()} connection requires authentication"
        )
    if not connection_health.remote_operations_allowed(health):
        raise RetryableJobError(
            f"{platform.title()} connection is temporarily unavailable"
        )
    try:
        if browser_connection and browser_connection["status"] == "connected":
            if platform == "hashnode":
                retrieval = runner.hashnode_browser_articles(
                    organization_id=browser_connection["skyvern_organization_id"],
                    profile_id=browser_connection["skyvern_profile_id"],
                )
                connection_health.record_operation_result(
                    context.store, context.user_id, platform, retrieval,
                )
                result = sync_hashnode_browser_records(
                    context.user_id, retrieval, store=context.store
                )
            else:
                retrieval = runner.medium_browser_articles(
                    organization_id=browser_connection["skyvern_organization_id"],
                    profile_id=browser_connection["skyvern_profile_id"],
                )
                connection_health.record_operation_result(
                    context.store, context.user_id, platform, retrieval,
                )
                result = sync_medium_browser_records(
                    context.user_id, retrieval, store=context.store
                )
        elif platform == "hashnode":
            token = context.store.get_connection_token(context.user_id, "hashnode")
            if not token or token == "cli_session":
                raise PermanentJobError("Hashnode connection is not available")
            result = sync_hashnode_articles(
                context.user_id, token, store=context.store
            )
        else:
            raise PermanentJobError("Medium browser connection is not available")
    except runner.RunnerUnavailable as exc:
        connection_health.record_unavailable(
            context.store, context.user_id, platform,
        )
        raise RetryableJobError(str(exc)) from exc
    if result["status"] == "failed":
        raise RetryableJobError(f"{platform.title()} synchronization failed")
    context.checkpoint(
        stage="synchronized",
        platform=platform,
        imported=result["imported"],
        updated=result["updated"],
        unchanged=result["unchanged"],
        failed=result["failed"],
    )
    return result


def handle_chat_turn(context: JobContext, payload: dict) -> dict:
    session_id = payload.get("session_id")
    revision_id = payload.get("article_revision_id")
    if not session_id or not revision_id:
        raise PermanentJobError("Chat turn job payload is incomplete")
    agent_chat.run_turn(
        user_id=context.user_id,
        session_id=session_id,
        article_revision_id=revision_id,
    )
    session = context.store.get_agent_session(context.user_id, session_id)
    if session is None:
        raise PermanentJobError("Agent session no longer exists")
    if session["status"] == "failed":
        raise PermanentJobError(session.get("error") or "Agent turn failed")
    context.checkpoint(stage="turn_completed", session_status=session["status"])
    return {"sessionId": session_id, "status": session["status"]}


def handle_browser_publish(context: JobContext, payload: dict) -> dict:
    run_id = payload.get("run_id")
    if not run_id:
        raise PermanentJobError("Browser publish job payload is incomplete")
    context.run_effect(
        f"browser-publish:{run_id}",
        lambda: browser_publish.execute_run(
            user_id=context.user_id, run_id=run_id
        ),
    )
    run = context.store.get_browser_publish_run(context.user_id, run_id)
    if run is None:
        raise PermanentJobError("Browser publish run no longer exists")
    if run["status"] == "failed":
        raise PermanentJobError(run.get("error") or "Browser publication failed")
    context.checkpoint(stage="browser_publish_completed", run_id=run_id)
    return {"runId": run_id, "status": run["status"], "result": run["result"]}


HANDLERS = {
    "generate": handle_generate,
    "push": handle_push,
    "inspect": handle_inspect,
    "regenerate": handle_regenerate,
    "sync": handle_sync,
    "chat_turn": handle_chat_turn,
    "browser_publish": handle_browser_publish,
}
