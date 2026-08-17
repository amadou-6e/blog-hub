"""Built-in durable job handlers."""
from __future__ import annotations

import re
from dataclasses import asdict

import backend.services.cli_runner as runner
from backend.services.agent_service import (
    GenerationError,
    generate_markdown,
    persist_generation,
)
from backend.services.push import push_article_to_platforms
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


HANDLERS = {
    "generate": handle_generate,
    "push": handle_push,
    "inspect": handle_inspect,
    "regenerate": handle_regenerate,
}
