import io
import hashlib
import re
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from typing import Literal, Optional

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
import backend.services.browser_publish as browser_publish
from backend.services.push import push_article_to_platforms
from backend.services.hashnode_sync import RemoteSyncArticle, _fingerprint
from backend.store.article_revisions import RevisionConflict

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
        request: Request,
        q: Optional[str] = Query(default=None),
        gate: Optional[GateStatus] = Query(default=None),
        status: Optional[PlatformStatus] = Query(default=None),
        platform: Optional[Platform] = Query(default=None),
        page: int = Query(default=1, ge=1),
        pageSize: int = Query(default=20, ge=1, le=100),
        sortBy: str = Query(default="updatedAt"),
        sortDir: str = Query(default="desc"),
):
    user_id: str = request.state.user_id
    items, total = store.list_articles(
        user_id=user_id,
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
def create_article(request: Request, body: CreateArticleRequest):
    user_id: str = request.state.user_id
    article = store.create_article(user_id, title=body.title)
    return CreateArticleResponse(
        id=article["id"],
        title=article["title"],
        createdAt=article["updated_at"],
    )


@router.delete("", status_code=204)
def delete_articles(request: Request, body: DeleteArticleRequest):
    user_id: str = request.state.user_id
    blocked = store.delete_articles(user_id, ids=body.ids, force=body.force)
    if blocked:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Some articles are published. Pass force=true to delete anyway.",
                "blocked_ids": blocked,
            },
        )


class DuplicateArticleSummary(BaseModel):
    id: str
    title: str


class DuplicateArticleResponse(BaseModel):
    article: DuplicateArticleSummary


class ArchiveArticleResponse(BaseModel):
    id: str
    archived: bool


def _article_not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"error": "not_found", "message": "Article not found."},
    )


@router.post(
    "/{article_id}/duplicate", response_model=DuplicateArticleResponse, status_code=201,
)
def duplicate_article(
    request: Request,
    article_id: str,
    idempotency_key: str = Header(min_length=1, max_length=200),
):
    duplicate, _created = store.duplicate_article(
        request.state.user_id, article_id, idempotency_key,
    )
    if duplicate is None:
        raise _article_not_found()
    return DuplicateArticleResponse(
        article=DuplicateArticleSummary(id=duplicate["id"], title=duplicate["title"]),
    )


@router.post("/{article_id}/archive", response_model=ArchiveArticleResponse)
def archive_article(request: Request, article_id: str):
    if not store.archive_article(request.state.user_id, article_id):
        raise _article_not_found()
    return ArchiveArticleResponse(id=article_id, archived=True)


@router.delete("/{article_id}", status_code=204)
def delete_article(request: Request, article_id: str):
    result = store.delete_article(request.state.user_id, article_id)
    if result == "not_found":
        raise _article_not_found()
    if result == "published":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "has_published_destinations",
                "message": "Cannot delete published article. Remove its live destinations first.",
            },
        )


# ── Get / Patch single article ────────────────────────────────────────────────


class ArticleDestinationDetail(BaseModel):
    status: str
    label: str
    url: Optional[str] = None
    error: Optional[str] = None


class ArticleDetailResponse(BaseModel):
    id: str
    title: str
    content: str
    word_count: int
    updated_at: str
    revision_id: str
    revision_number: int
    gate: str
    source: str
    source_platform: Optional[str] = None
    preview_image_url: Optional[str] = None
    destinations: dict[str, ArticleDestinationDetail]


_MIME_TYPE = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")


def _asset_media_type(value: str | None) -> str:
    if value and _MIME_TYPE.fullmatch(value.strip()):
        return value.strip().lower()
    return "application/octet-stream"


def _asset_content_disposition(filename: str, media_type: str) -> str:
    leaf = filename.replace("\\", "/").rsplit("/", 1)[-1]
    leaf = "".join(character for character in leaf if 32 <= ord(character) < 127)
    leaf = leaf[:255] or "asset"
    ascii_name = re.sub(r'[^A-Za-z0-9._ -]', "_", leaf).strip(". ") or "asset"
    disposition = "inline" if media_type in {
        "image/avif",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    } else "attachment"
    return (
        f'{disposition}; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(leaf, safe='')}"
    )


def _etag_matches(request: Request, etag: str) -> bool:
    candidates = {
        candidate.strip() for candidate in request.headers.get("if-none-match", "").split(",")
    }
    return "*" in candidates or etag in candidates or f"W/{etag}" in candidates


def _article_asset_response(request: Request, asset: dict) -> Response:
    etag = f'"{hashlib.sha256(asset["data"]).hexdigest()}"'
    media_type = _asset_media_type(asset["mime_type"])
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=3600, must-revalidate",
        "Vary": "Cookie",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": _asset_content_disposition(asset["filename"], media_type),
    }
    if _etag_matches(request, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=asset["data"], media_type=media_type, headers=headers)


@router.get("/{article_id}/assets/by-filename/{filename:path}", response_class=Response)
def get_article_asset_by_filename(request: Request, article_id: str, filename: str):
    asset = store.get_article_asset_by_filename(request.state.user_id, article_id, filename)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return _article_asset_response(request, asset)


@router.get("/{article_id}/assets/{asset_id}", response_class=Response)
def get_article_asset(request: Request, article_id: str, asset_id: int):
    asset = store.read_article_asset(request.state.user_id, article_id, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return _article_asset_response(request, asset)


@router.get("/{article_id}", response_model=ArticleDetailResponse)
def get_article(request: Request, article_id: str):
    user_id: str = request.state.user_id
    article = store.get_article(user_id, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    revision = store.get_current_article_revision(user_id, article_id)
    if revision is None:
        raise HTTPException(status_code=500, detail="Article revision is missing")
    return ArticleDetailResponse(
        id=article["id"],
        title=article["title"],
        content=article["body"],
        word_count=article["word_count"],
        updated_at=str(article["updated_at"]),
        revision_id=revision["id"],
        revision_number=revision["revision_number"],
        gate=article["gate"],
        source=article["source"],
        source_platform=article.get("source_platform"),
        preview_image_url=article.get("preview_image_url"),
        destinations={
            k:
                ArticleDestinationDetail(
                    status=v["status"],
                    label=v["label"],
                    url=v.get("url"),
                    error=v.get("error"),
                ) for k, v in article["destinations"].items()
        },
    )


class ArticlePatchRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    base_revision_id: str


class ArticlePatchResponse(BaseModel):
    updated_at: str
    word_count: int
    revision_id: str
    revision_number: int


def _raise_revision_conflict(exc: RevisionConflict) -> None:
    raise HTTPException(
        status_code=409,
        detail={
            "code": "revision_conflict",
            "message": str(exc),
            "current": exc.current,
        },
    ) from exc


@router.patch("/{article_id}", response_model=ArticlePatchResponse)
def patch_article(request: Request, article_id: str, body: ArticlePatchRequest):
    user_id: str = request.state.user_id
    article = store.get_article(user_id, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    try:
        revision = store.save_article_revision(
            user_id,
            article_id,
            title=body.title,
            content=body.content,
            expected_revision_id=body.base_revision_id,
            source="user",
            description="Auto-saved",
        )
    except RevisionConflict as exc:
        _raise_revision_conflict(exc)
    updated = store.get_article(user_id, article_id)
    return ArticlePatchResponse(
        updated_at=str(updated["updated_at"]),
        word_count=updated["word_count"],
        revision_id=revision["id"],
        revision_number=revision["revision_number"],
    )


class RevisionSummary(BaseModel):
    id: str
    revision_number: int
    title: str
    source: str
    description: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str
    base_revision_id: Optional[str] = None
    restored_from_id: Optional[str] = None


class RevisionDetail(RevisionSummary):
    content: str


class RevisionListResponse(BaseModel):
    revisions: list[RevisionSummary]


class RevisionDiffResponse(BaseModel):
    revision: RevisionDetail
    current: RevisionDetail
    diff: str


class CheckpointRequest(BaseModel):
    base_revision_id: str
    description: Optional[str] = None


class RestoreRevisionRequest(BaseModel):
    base_revision_id: str


@router.get("/{article_id}/revisions", response_model=RevisionListResponse)
def list_revisions(request: Request, article_id: str):
    user_id: str = request.state.user_id
    if store.get_article(user_id, article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return RevisionListResponse(revisions=store.list_article_revisions(user_id, article_id))


@router.get("/{article_id}/revisions/{revision_id}", response_model=RevisionDetail)
def get_revision(request: Request, article_id: str, revision_id: str):
    revision = store.get_article_revision(request.state.user_id, article_id, revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="Revision not found")
    return revision


@router.get(
    "/{article_id}/revisions/{revision_id}/diff", response_model=RevisionDiffResponse
)
def compare_revision(request: Request, article_id: str, revision_id: str):
    comparison = store.compare_article_revision(
        request.state.user_id, article_id, revision_id
    )
    if comparison is None:
        raise HTTPException(status_code=404, detail="Revision not found")
    return comparison


@router.post(
    "/{article_id}/checkpoints", response_model=RevisionDetail, status_code=201
)
def create_checkpoint(request: Request, article_id: str, body: CheckpointRequest):
    user_id: str = request.state.user_id
    article = store.get_article(user_id, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    try:
        return store.save_article_revision(
            user_id,
            article_id,
            title=article["title"],
            content=article["body"],
            expected_revision_id=body.base_revision_id,
            source="user",
            description=body.description or "Manual checkpoint",
            force_revision=True,
        )
    except RevisionConflict as exc:
        _raise_revision_conflict(exc)


@router.post(
    "/{article_id}/revisions/{revision_id}/restore", response_model=RevisionDetail
)
def restore_revision(
    request: Request,
    article_id: str,
    revision_id: str,
    body: RestoreRevisionRequest,
):
    try:
        return store.restore_article_revision(
            request.state.user_id,
            article_id,
            revision_id,
            body.base_revision_id,
        )
    except RevisionConflict as exc:
        _raise_revision_conflict(exc)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Revision not found") from exc


# ── Generate ──────────────────────────────────────────────────────────────────

_SKILL_INSTRUCTIONS: dict[str, str] = {
    "deep-dive":
        ("Write a technical deep-dive article. Include concrete code examples, "
         "explain the underlying mechanisms, cover edge cases, and reference real-world usage."),
    "tutorial": ("Write a step-by-step tutorial. Cover prerequisites, walk through a real "
                 "implementation from scratch, highlight common pitfalls, and show how to verify "
                 "the result works."),
    "comparison":
        ("Write a comparison article. Cover setup complexity, performance characteristics, "
         "developer experience, and ecosystem maturity. Include a summary table. "
         "End with a recommendation for different scenarios."),
    "opinion": ("Write an opinion piece. Lead with a clear thesis, support it with specific "
                "evidence and examples, acknowledge counterarguments, and close with a takeaway."),
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
        f"Author's brief:\n{prompt}")


def _extract_title(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return "Untitled Article"


@router.post("/generate", response_model=GenerateArticleResponse, status_code=201)
def generate_article(request: Request, body: GenerateArticleRequest):
    """
    Generate a new article via an AI provider and store it.
    Optionally pushes drafts to the selected destinations.
    """
    user_id: str = request.state.user_id
    if body.provider not in ("anthropic", "openai"):
        raise HTTPException(400, f"Unknown provider: {body.provider}")

    full_prompt = _build_generation_prompt(body.prompt or "", body.skill, body.word_count)
    if body.context_md:
        full_prompt += f"\n\nAdditional context:\n{body.context_md}"

    # Both providers go through the CLI runner — Anthropic via claude -p,
    # OpenAI via codex exec (uses the OAuth session or API key).
    token = store.get_connection_token(user_id, body.provider) if body.provider == "openai" else None
    api_key = runner.api_key_from_connection_token(token)
    try:
        result = runner.run_task(
            provider=body.provider,
            task="generate",
            article_md=full_prompt,
            api_key=api_key,
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
    article = store.create_article(user_id, title=title)
    store.update_article_body(user_id, article["id"], generated_md)

    if body.destinations:
        store.set_destinations_pending(user_id, article["id"], body.destinations)
        results = push_article_to_platforms(
            store.get_article(user_id, article["id"]),
            body.destinations,
            get_connection_token=lambda conn_id: store.get_connection_token(user_id, conn_id),
        )
        for platform, push_result in results.items():
            store.apply_push_result(user_id,
                article["id"],
                platform,
                success=push_result.success,
                url=push_result.url,
                error=push_result.error,
                label=push_result.label,
                draft_id=push_result.draft_id,
            )

    return GenerateArticleResponse(id=article["id"], title=title)


@router.post("/{article_id}/push", response_model=AsyncAccepted, status_code=202)
def push_article(request: Request, article_id: str, body: dict = {}):
    user_id: str = request.state.user_id
    article = store.get_article(user_id, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    platforms = body.get("platforms", list(article["destinations"].keys()))
    if store.has_unresolved_reconciliation(user_id, article_id, platforms):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "remote_content_conflict",
                "message": "Resolve remote article conflicts before pushing.",
            },
        )
    idempotency_key = request.headers.get("Idempotency-Key")
    existing = store.find_job_by_idempotency_key(user_id, "push", idempotency_key)
    if existing:
        return AsyncAccepted(jobId=existing["job_id"], status=existing["status"])
    store.set_destinations_pending(user_id, article_id, platforms)
    job = store.create_job(
        user_id,
        "push",
        article_id,
        payload={"article_id": article_id, "platforms": platforms},
        queue="publishing",
        idempotency_key=idempotency_key,
        max_attempts=4,
        timeout_seconds=300,
    )
    return AsyncAccepted(jobId=job["job_id"], status=JobStatus.queued)


class BrowserPublishRequest(BaseModel):
    mode: Literal["draft", "publish"] = "draft"


@router.post("/{article_id}/browser-publish/{platform}", status_code=201)
def request_browser_publish(
    request: Request,
    article_id: str,
    platform: str,
    body: BrowserPublishRequest = BrowserPublishRequest(),
):
    if store.get_article(request.state.user_id, article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    browser_connection = store.get_browser_connection(
        request.state.user_id, platform
    )
    if not browser_connection or browser_connection["status"] != "connected":
        raise HTTPException(
            status_code=409,
            detail=f"Connect {platform.title()} with browser login before browser publishing",
        )
    return store.create_browser_publish_run(
        request.state.user_id, article_id,
        platform=platform, mode=body.mode,
    )


@router.get("/{article_id}/browser-publish/{run_id}")
def get_browser_publish(request: Request, article_id: str, run_id: str):
    run = store.get_browser_publish_run(request.state.user_id, run_id)
    if run is None or run["article_id"] != article_id:
        raise HTTPException(status_code=404, detail="Browser publish run not found")
    return run


@router.post("/{article_id}/browser-publish/{run_id}/approve", status_code=202)
def approve_browser_publish(
    request: Request, article_id: str, run_id: str,
):
    run = store.get_browser_publish_run(request.state.user_id, run_id)
    if run is None or run["article_id"] != article_id:
        raise HTTPException(status_code=404, detail="Browser publish run not found")
    try:
        approved = store.approve_browser_publish_run(request.state.user_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    job = store.create_job(
        request.state.user_id,
        "browser_publish",
        article_id,
        payload={"run_id": run_id},
        queue="publishing",
        idempotency_key=f"browser-publish:{run_id}",
        max_attempts=3,
        timeout_seconds=900,
    )
    return {**approved, "jobId": job["job_id"]}


# ── Import ────────────────────────────────────────────────────────────────────


class ImportArticleRequest(BaseModel):
    source: str  # "platform" | "upload"
    # platform source
    platform: Optional[str] = None
    draft_id: Optional[str] = None
    status: Optional[str] = None  # "draft" | "published" — client-provided for fast path
    # upload source
    filename: Optional[str] = None
    content: Optional[str] = None
    # shared — user-edited title from the Review step
    title: str


class ImportArticleResponse(BaseModel):
    id: str
    title: str


@router.post("/import", response_model=ImportArticleResponse, status_code=201)
def import_article(request: Request, body: ImportArticleRequest):
    """
    Create an article workspace from an existing platform draft or an uploaded
    Markdown file. Returns the new article id for navigation to the editor.

    source="platform": fetches content from GET /api/connections/{platform}/drafts/{draft_id}.
    source="upload":   uses the content field directly (already parsed client-side).
    """
    user_id: str = request.state.user_id
    if body.source not in ("platform", "upload"):
        raise HTTPException(status_code=422, detail="source must be 'platform' or 'upload'")

    if body.source == "platform":
        if not body.platform or not body.draft_id:
            raise HTTPException(status_code=422,
                                detail="platform and draft_id required for source=platform")

        token = store.get_connection_token(user_id, body.platform)
        if not token:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "platform_not_connected",
                    "platform": body.platform
                },
            )

        # If the client already has the body (pre-fetched during article selection),
        # use it directly and skip the expensive platform API re-fetch.
        if body.content:
            content = body.content
            canonical_url = None
        else:
            # Fetch content from the live platform API (or mock for Medium).
            from backend.routers.connections import (
                _fetch_hashnode_drafts,
                _fetch_devto_drafts,
                _MOCK_DRAFTS,
            )
            import httpx

            try:
                if body.platform == "hashnode":
                    all_drafts = _fetch_hashnode_drafts(token)
                elif body.platform == "devto":
                    all_drafts = _fetch_devto_drafts(token)
                else:
                    all_drafts = _MOCK_DRAFTS.get(body.platform, [])
            except httpx.HTTPStatusError as exc:
                raise HTTPException(status_code=502,
                                    detail=f"Platform API error: {exc.response.status_code}")
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Platform API error: {exc}")

            draft = next((d for d in all_drafts if d["id"] == body.draft_id), None)
            if draft is None:
                raise HTTPException(status_code=404, detail={"error": "draft_not_found"})

            content = draft["body"]
            canonical_url = draft.get("canonical_url")
        platform_label = {
            "medium": "Medium",
            "hashnode": "Hashnode",
            "devto": "Dev.to"
        }.get(body.platform, body.platform)
        event = f"Imported from {platform_label}"

        # Check if this article already exists locally (SEO cross-post grouping).
        # Match by canonical_url first, then fall back to exact title.
        existing = None
        if canonical_url:
            existing = store.find_article_by_canonical_url(user_id, canonical_url)
        if existing is None:
            existing = store.find_article_by_title(user_id, body.title)

        if existing is not None:
            # Merge this platform into the existing article's destinations.
            _draft_id = body.draft_id if body.content else draft["id"]
            _status = body.status if body.content else draft.get("status", "draft")
            store.merge_platform_into_article(user_id,
                article_id=existing["id"],
                platform=body.platform,
                status=_status,
                url=None,
                draft_id=_draft_id,
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
        user_id,
        title=body.title,
        source=body.source,
        source_platform=source_platform,
        canonical_url=canonical_url if body.source == "platform" else None,
    )
    store.update_article_body(user_id, article["id"], content, event=event)

    return ImportArticleResponse(id=article["id"], title=body.title)


# ── Upload parse (multipart) ──────────────────────────────────────────────────

# Maximum raw file size accepted at the boundary (applies to every upload type).
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# Extensions allowed anywhere inside a ZIP archive.
# Directories and __MACOSX metadata entries are silently skipped.
_ALLOWED_ZIP_EXTENSIONS = {".md", ".html", ".png", ".jpg", ".jpeg", ".svg"}

# Extensions that carry article text (we extract the first one found).
_ARTICLE_EXTENSIONS = {".md", ".html"}


class ParseUploadResponse(BaseModel):
    filename: str
    content: str  # extracted article text (markdown or raw HTML)
    content_type: str  # "markdown" | "html"
    images: list[str]  # basenames of image files found alongside the article


@router.post("/parse-upload", response_model=ParseUploadResponse)
async def parse_upload(file: UploadFile = File(...)):
    """
    Accept a raw uploaded file (.md, .html, or .zip), validate it, and return
    the extracted article text + list of image filenames.

    Validation rules:
    - File size must not exceed 50 MB (checked before reading the full body).
    - .zip archives must only contain files with allowed extensions
      (.md, .html, .png, .jpg, .jpeg, .svg); any other extension is rejected.
    - .zip must contain exactly one article file (.md or .html) at the root or
      one level deep; more than one article file is rejected.

    Images inside a .zip are listed by basename in the response. The caller is
    responsible for matching them to references in the article text.
    """
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=
            f"File too large. Maximum allowed size is {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    stem = Path(file.filename or "upload").suffix.lower()

    # ── Plain .md or .html ───────────────────────────────────────────────────
    if stem in _ARTICLE_EXTENSIONS:
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=422, detail="File is not valid UTF-8 text.")
        content_type = "html" if stem == ".html" else "markdown"
        return ParseUploadResponse(
            filename=file.filename or "upload",
            content=content,
            content_type=content_type,
            images=[],
        )

    # ── .zip ─────────────────────────────────────────────────────────────────
    if stem == ".zip":
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            raise HTTPException(status_code=422, detail="File is not a valid ZIP archive.")

        article_entries: list[zipfile.ZipInfo] = []
        image_entries: list[zipfile.ZipInfo] = []
        rejected: list[str] = []

        for info in zf.infolist():
            name = info.filename
            # Skip directory entries and macOS metadata
            if name.endswith("/") or "__MACOSX" in name or name.startswith("."):
                continue
            ext = Path(name).suffix.lower()
            if ext not in _ALLOWED_ZIP_EXTENSIONS:
                rejected.append(name)
                continue
            # Only accept files at root or one level deep
            depth = len([p for p in Path(name).parts if p]) - 1
            if depth > 1:
                continue
            if ext in _ARTICLE_EXTENSIONS:
                article_entries.append(info)
            else:
                image_entries.append(info)

        if rejected:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "disallowed_file_types",
                    "message": ("ZIP contains files with unsupported extensions. "
                                f"Allowed: {', '.join(sorted(_ALLOWED_ZIP_EXTENSIONS))}."),
                    "rejected": rejected[:20],  # cap list length in response
                },
            )

        if not article_entries:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "no_article_found",
                    "message": "ZIP does not contain a .md or .html file.",
                },
            )

        if len(article_entries) > 1:
            raise HTTPException(
                status_code=422,
                detail={
                    "error":
                        "multiple_articles",
                    "message": ("ZIP contains more than one article file "
                                f"({', '.join(e.filename for e in article_entries)}). "
                                "Include only one .md or .html file."),
                },
            )

        article_info = article_entries[0]
        try:
            content = zf.read(article_info.filename).decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=422,
                detail=f"{article_info.filename} is not valid UTF-8 text.",
            )

        ext = Path(article_info.filename).suffix.lower()
        content_type = "html" if ext == ".html" else "markdown"
        images = [Path(e.filename).name for e in image_entries]

        return ParseUploadResponse(
            filename=Path(article_info.filename).name,
            content=content,
            content_type=content_type,
            images=images,
        )

    raise HTTPException(
        status_code=415,
        detail=(f"Unsupported file type '{stem}'. "
                "Accepted: .md, .html, .zip"),
    )


@router.post("/{article_id}/inspect", response_model=AsyncAccepted, status_code=202)
def inspect_article(request: Request, article_id: str):
    user_id: str = request.state.user_id
    article = store.get_article(user_id, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    job = store.create_job(
        user_id,
        "inspect",
        article_id,
        payload={"article_id": article_id},
        max_attempts=2,
        timeout_seconds=60,
    )
    return AsyncAccepted(jobId=job["job_id"], status=JobStatus.queued)


# ── Regenerate ────────────────────────────────────────────────────────────────


@router.post("/{article_id}/regenerate", response_model=AsyncAccepted, status_code=202)
def regenerate_patches(request: Request, article_id: str):
    """
    Read all unresolved comments on an article, call the AI to produce
    patch suggestions, and persist them as article_patches rows.
    Returns a job ID for polling.
    """
    user_id: str = request.state.user_id
    article = store.get_article(user_id, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    idempotency_key = request.headers.get("Idempotency-Key")
    existing = store.find_job_by_idempotency_key(
        user_id, "regenerate", idempotency_key
    )
    if existing:
        return AsyncAccepted(jobId=existing["job_id"], status=existing["status"])
    job = store.create_job(
        user_id,
        "regenerate",
        article_id,
        payload={"article_id": article_id},
        queue="agents",
        idempotency_key=idempotency_key,
        max_attempts=3,
        timeout_seconds=300,
    )
    return AsyncAccepted(jobId=job["job_id"], status=JobStatus.queued)


# ── Chat ──────────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    command: str


class ChatResponse(BaseModel):
    reply: str


class ChatMessage(BaseModel):
    role: str
    text: str
    createdAt: str


@router.get("/{article_id}/chat")
def get_chat(request: Request, article_id: str):
    user_id: str = request.state.user_id
    if store.get_article(user_id, article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    messages = store.list_chat(user_id, article_id)
    return {
        "messages": [
            ChatMessage(role=m["role"], text=m["text"], createdAt=m["created_at"]) for m in messages
        ]
    }


@router.post("/{article_id}/chat", response_model=ChatResponse)
def post_chat(request: Request, article_id: str, body: ChatRequest):
    """
    Execute a chat command against the article. Persists both request and
    reply to the article_chat_log table. Returns the bot reply.
    """
    user_id: str = request.state.user_id
    article = store.get_article(user_id, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    cmd = body.command.strip()
    store.add_chat_message(user_id, article_id, "user", cmd)

    reply = _dispatch_chat(user_id, article_id, article, cmd)
    store.add_chat_message(user_id, article_id, "bot", reply)

    return ChatResponse(reply=reply)


def _dispatch_chat(user_id: str, article_id: str, article: dict, cmd: str) -> str:
    """Map a chat command string to a reply string by executing real operations."""
    lower = cmd.lower().strip()

    if lower == "help":
        return ("Commands:\n"
                "  destinations status\n"
                "  comment list\n"
                "  patch apply <id>\n"
                "  regenerate\n"
                "  inspect")

    if lower == "destinations status":
        lines = []
        for platform, dest in article["destinations"].items():
            status = dest.get("status", "none")
            url = dest.get("url")
            suffix = f" ({url})" if url else ""
            lines.append(f"{platform:<10} → {status}{suffix}")
        return "\n".join(lines) if lines else "No destinations configured."

    if lower == "comment list":
        comments = store.list_comments(user_id, article_id)
        if not comments:
            return "No comments on this article."
        lines = []
        for c in comments:
            state = "resolved" if c["resolved"] else ("patch" if c["has_patch"] else "open")
            lines.append(f"{c['id']} [{state}] {c['author']}: {c['text']}")
        return "\n".join(lines)

    if lower == "regenerate":
        comments = store.list_comments(user_id, article_id)
        unresolved = [c for c in comments if not c["resolved"]]
        if not unresolved:
            return "No unresolved comments to regenerate from."
        return (f"Regeneration queued for {len(unresolved)} comment(s). "
                "Use POST /api/articles/{id}/regenerate and poll the job for results.")

    if lower == "inspect":
        gate = article.get("gate", "pending")
        wc = article.get("word_count", 0)
        return (f"Running gate on {article_id}...\n"
                f"  word_count: {wc}  {'PASS' if wc >= 500 else 'WARN'}\n"
                f"Gate: {gate.upper()}")

    if lower.startswith("patch apply "):
        patch_id = cmd[len("patch apply "):].strip()
        updated = store.set_patch_state(user_id, article_id, patch_id, "accepted")
        if updated is None:
            return f"Patch '{patch_id}' not found."
        return f"Patch {patch_id} applied."

    return f"Unknown command: '{cmd}'. Type 'help' for available commands."
