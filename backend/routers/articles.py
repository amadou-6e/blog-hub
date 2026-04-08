from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from pydantic import BaseModel

from backend.schemas.overview import (
    ArticleListResponse,
    ArticleSummary,
    AsyncAccepted,
    CreateArticleRequest,
    CreateArticleResponse,
    DeleteArticleRequest,
    GateStatus,
    JobStatus,
    Platform,
    PlatformStatus,
    TimelineEvent,
)
import backend.store as store
import backend.services.cli_runner as runner
from backend.services.push import push_article_to_platforms

router = APIRouter(prefix="/api/articles", tags=["articles"])


def _article_to_schema(a: dict) -> ArticleSummary:
    return ArticleSummary(
        id=a["id"],
        title=a["title"],
        updatedAt=a["updated_at"],
        wordCount=a["word_count"],
        gate=a["gate"],
        previewImageUrl=a.get("preview_image_url"),
        source=a.get("source", "native"),
        sourcePlatform=a.get("source_platform"),
        destinations={
            Platform(k):
                PlatformStatus.__members__.get(v["status"], PlatformStatus.none) and __import__(
                    "backend.schemas.overview", fromlist=["PlatformSummary"]).PlatformSummary(**v)
            for k, v in a["destinations"].items()
        },
        recentTimeline=[
            TimelineEvent(timestamp=e["timestamp"], event=e["event"]) for e in a["recent_timeline"]
        ],
    )


@router.get("", response_model=ArticleListResponse)
def list_articles(
        q: Optional[str] = Query(default=None),
        gate: Optional[GateStatus] = Query(default=None),
        status: Optional[PlatformStatus] = Query(default=None),
        platform: Optional[Platform] = Query(default=None),
        page: int = Query(default=1, ge=1),
        pageSize: int = Query(default=20, ge=1, le=100),
        sortBy: str = Query(default="updatedAt"),
        sortDir: str = Query(default="desc"),
):
    items, total = store.list_articles(
        q=q,
        gate=gate.value if gate else None,
        status=status.value if status else None,
        platform=platform.value if platform else None,
        page=page,
        page_size=pageSize,
        sort_by=sortBy,
        sort_dir=sortDir,
    )
    return ArticleListResponse(
        items=[_article_to_schema(a) for a in items],
        total=total,
        page=page,
        pageSize=pageSize,
    )


@router.post("", response_model=CreateArticleResponse, status_code=201)
def create_article(body: CreateArticleRequest):
    article = store.create_article(title=body.title)
    return CreateArticleResponse(
        id=article["id"],
        title=article["title"],
        createdAt=article["updated_at"],
    )


@router.delete("", status_code=204)
def delete_articles(body: DeleteArticleRequest):
    blocked = store.delete_articles(ids=body.ids, force=body.force)
    if blocked:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Some articles are published. Pass force=true to delete anyway.",
                "blocked_ids": blocked,
            },
        )


# ── Generate ──────────────────────────────────────────────────────────────────

_SKILL_INSTRUCTIONS: dict[str, str] = {
    "deep-dive": (
        "Write a technical deep-dive article. Include concrete code examples, "
        "explain the underlying mechanisms, cover edge cases, and reference real-world usage."
    ),
    "tutorial": (
        "Write a step-by-step tutorial. Cover prerequisites, walk through a real "
        "implementation from scratch, highlight common pitfalls, and show how to verify "
        "the result works."
    ),
    "comparison": (
        "Write a comparison article. Cover setup complexity, performance characteristics, "
        "developer experience, and ecosystem maturity. Include a summary table. "
        "End with a recommendation for different scenarios."
    ),
    "opinion": (
        "Write an opinion piece. Lead with a clear thesis, support it with specific "
        "evidence and examples, acknowledge counterarguments, and close with a takeaway."
    ),
}


class GenerateArticleRequest(BaseModel):
    prompt: str
    skill: str = "deep-dive"
    provider: str = "anthropic"
    word_count: int = 1500
    context_md: Optional[str] = None
    destinations: list[str] = []


class GenerateArticleResponse(BaseModel):
    id: str
    title: str


def _build_generation_prompt(prompt: str, skill: str, word_count: int) -> str:
    instructions = _SKILL_INSTRUCTIONS.get(skill, _SKILL_INSTRUCTIONS["deep-dive"])
    return (
        "You are a technical writer producing a blog article for a developer audience.\n\n"
        f"{instructions}\n\n"
        f"Target length: approximately {word_count} words.\n\n"
        "Output the article in Markdown. The first line must be a # Title. "
        "Write the complete article — do not stop early or add any commentary outside the article itself.\n\n"
        f"Author's brief:\n{prompt}"
    )


def _extract_title(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return "Untitled Article"



@router.post("/generate", response_model=GenerateArticleResponse, status_code=201)
def generate_article(body: GenerateArticleRequest):
    """
    Generate a new article via an AI provider and store it.
    Optionally pushes drafts to the selected destinations.
    """
    if body.provider not in ("anthropic", "openai"):
        raise HTTPException(400, f"Unknown provider: {body.provider}")

    full_prompt = _build_generation_prompt(body.prompt or "", body.skill, body.word_count)
    if body.context_md:
        full_prompt += f"\n\nAdditional context:\n{body.context_md}"

    # Both providers go through the CLI runner — Anthropic via claude -p,
    # OpenAI via codex exec (uses the OAuth session from codex login).
    try:
        result = runner.run_task(
            provider=body.provider,
            task="generate",
            article_md=full_prompt,
        )
    except runner.RunnerUnavailable as exc:
        raise HTTPException(503, str(exc))
    if result["exit_code"] != 0:
        err_detail = (result.get("stderr") or result.get("stdout") or "unknown error")[:500]
        raise HTTPException(502, f"Generation failed: {err_detail}")
    generated_md = result["stdout"]

    if not generated_md.strip():
        raise HTTPException(502, "Generation produced empty output")

    title = _extract_title(generated_md)
    article = store.create_article(title=title)
    store.update_article_body(article["id"], generated_md)

    if body.destinations:
        store.set_destinations_pending(article["id"], body.destinations)
        results = push_article_to_platforms(
            store.get_article(article["id"]),
            body.destinations,
            get_connection_token=store.get_connection_token,
        )
        for platform, push_result in results.items():
            store.apply_push_result(
                article["id"], platform,
                success=push_result.success,
                url=push_result.url,
                error=push_result.error,
                label=push_result.label,
                draft_id=push_result.draft_id,
            )

    return GenerateArticleResponse(id=article["id"], title=title)


@router.post("/{article_id}/push", response_model=AsyncAccepted, status_code=202)
def push_article(article_id: str, body: dict = {}):
    article = store.get_article(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    platforms = body.get("platforms", list(article["destinations"].keys()))
    store.set_destinations_pending(article_id, platforms)
    job = store.create_job("push", article_id)

    results = push_article_to_platforms(
        article,
        platforms,
        get_connection_token=store.get_connection_token,
    )
    job_result: dict[str, dict] = {}
    for platform, result in results.items():
        store.apply_push_result(
            article_id,
            platform,
            success=result.success,
            url=result.url,
            error=result.error,
            label=result.label,
            draft_id=result.draft_id,
        )
        job_result[platform] = {
            "status": result.status,
            "label": result.label,
            "url": result.url,
            "error": result.error,
            "draft_id": result.draft_id,
        }
    store.complete_job(job["job_id"], result=job_result)

    return AsyncAccepted(jobId=job["job_id"], status=JobStatus.done)


# ── Import ────────────────────────────────────────────────────────────────────

class ImportArticleRequest(BaseModel):
    source: str                        # "platform" | "upload"
    # platform source
    platform: Optional[str] = None
    draft_id: Optional[str] = None
    # upload source
    filename: Optional[str] = None
    # shared fields
    content: Optional[str] = None     # pre-fetched body (platform) or parsed MD (upload)
    title: str
    status: Optional[str] = None      # "draft" | "published" — from platform draft
    cover_image: Optional[str] = None # cover image URL from platform


class ImportArticleResponse(BaseModel):
    id: str
    title: str


@router.post("/import", response_model=ImportArticleResponse, status_code=201)
def import_article(body: ImportArticleRequest):
    """
    Create an article workspace from an existing platform draft or an uploaded
    Markdown file. Returns the new article id for navigation to the editor.

    source="platform": uses body.content (pre-fetched by the client on the Review step).
                       Falls back to fetching via GET /api/connections/{platform}/drafts/{draft_id}
                       if body.content is absent.
    source="upload":   uses body.content directly (already parsed client-side).
    """
    if body.source not in ("platform", "upload"):
        raise HTTPException(status_code=422, detail="source must be 'platform' or 'upload'")

    if body.source == "platform":
        if not body.platform or not body.draft_id:
            raise HTTPException(status_code=422, detail="platform and draft_id required for source=platform")

        platform_label = {"medium": "Medium", "hashnode": "Hashnode", "devto": "Dev.to"}.get(
            body.platform, body.platform
        )
        event = f"Imported from {platform_label}"

        if body.content:
            # Client pre-fetched the body on the Review step — use it directly.
            content = body.content
            canonical_url = None  # not available without a separate API call
        else:
            # Fallback: fetch content from the connections router.
            token = store.get_connection_token(body.platform)
            if not token:
                raise HTTPException(
                    status_code=404,
                    detail={"error": "platform_not_connected", "platform": body.platform},
                )
            from backend.routers.connections import _fetch_draft
            draft = _fetch_draft(body.platform, body.draft_id, token)
            if draft is None:
                raise HTTPException(status_code=404, detail={"error": "draft_not_found"})
            content = draft["body"]
            canonical_url = draft.get("canonical_url")

        # Deduplication: match by canonical_url then exact title.
        canonical_url = getattr(body, "canonical_url", None) or (
            canonical_url if not body.content else None
        )
        existing = None
        if canonical_url:
            existing = store.find_article_by_canonical_url(canonical_url)
        if existing is None:
            existing = store.find_article_by_title(body.title)

        if existing is not None:
            store.merge_platform_into_article(
                article_id=existing["id"],
                platform=body.platform,
                status=body.status or "draft",
                url=None,
                draft_id=body.draft_id,
                event=event,
            )
            return ImportArticleResponse(id=existing["id"], title=existing["title"])

    else:  # upload
        if not body.content:
            raise HTTPException(status_code=422, detail="content required for source=upload")
        content = body.content
        canonical_url = None
        filename = body.filename or "upload.md"
        event = f"Uploaded from {filename}"

    source_platform = body.platform if body.source == "platform" else None
    article = store.create_article(
        title=body.title,
        source=body.source,
        source_platform=source_platform,
        canonical_url=canonical_url if body.source == "platform" else None,
    )
    store.update_article_body(article["id"], content, event=event)

    return ImportArticleResponse(id=article["id"], title=body.title)


@router.post("/{article_id}/inspect", response_model=AsyncAccepted, status_code=202)
def inspect_article(article_id: str):
    article = store.get_article(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    job = store.create_job("inspect", article_id)

    # Simulate: word count >= 500 → pass, else warn
    gate = "pass" if article["word_count"] >= 500 else "warn"
    store.apply_inspect_result(article_id, gate)
    store.complete_job(job["job_id"], result={"gate": gate})

    return AsyncAccepted(jobId=job["job_id"], status=JobStatus.done)
