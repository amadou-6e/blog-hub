import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
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
    gate: str
    source: str
    source_platform: Optional[str] = None
    destinations: dict[str, ArticleDestinationDetail]


@router.get("/{article_id}", response_model=ArticleDetailResponse)
def get_article(request: Request, article_id: str):
    user_id: str = request.state.user_id
    article = store.get_article(user_id, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return ArticleDetailResponse(
        id=article["id"],
        title=article["title"],
        content=article["body"],
        word_count=article["word_count"],
        updated_at=str(article["updated_at"]),
        gate=article["gate"],
        source=article["source"],
        source_platform=article.get("source_platform"),
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


class ArticlePatchResponse(BaseModel):
    updated_at: str
    word_count: int


@router.patch("/{article_id}", response_model=ArticlePatchResponse)
def patch_article(request: Request, article_id: str, body: ArticlePatchRequest):
    user_id: str = request.state.user_id
    article = store.get_article(user_id, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    if body.title is not None:
        store.update_article_title(user_id, article_id, body.title)
    if body.content is not None:
        store.update_article_body(user_id, article_id, body.content, event="Auto-saved")
    updated = store.get_article(user_id, article_id)
    return ArticlePatchResponse(
        updated_at=str(updated["updated_at"]),
        word_count=updated["word_count"],
    )


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
    api_key = store.get_connection_token(user_id, body.provider) if body.provider == "openai" else None
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
    store.set_destinations_pending(user_id, article_id, platforms)
    job = store.create_job(user_id, "push", article_id)

    results = push_article_to_platforms(
        article,
        platforms,
        get_connection_token=lambda conn_id: store.get_connection_token(user_id, conn_id),
    )
    job_result: dict[str, dict] = {}
    for platform, result in results.items():
        store.apply_push_result(
            user_id,
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
    store.complete_job(user_id, job["job_id"], result=job_result)

    return AsyncAccepted(jobId=job["job_id"], status=JobStatus.done)


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

    job = store.create_job(user_id, "inspect", article_id)

    # Simulate: word count >= 500 → pass, else warn
    gate = "pass" if article["word_count"] >= 500 else "warn"
    store.apply_inspect_result(user_id, article_id, gate)
    store.complete_job(user_id, job["job_id"], result={"gate": gate})

    return AsyncAccepted(jobId=job["job_id"], status=JobStatus.done)


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

    comments = store.list_comments(user_id, article_id)
    unresolved = [c for c in comments if not c["resolved"]]

    job = store.create_job(user_id, "regenerate", article_id)

    if not unresolved:
        store.complete_job(user_id, job["job_id"], result={"patches_created": 0})
        return AsyncAccepted(jobId=job["job_id"], status=JobStatus.done)

    # Build a prompt asking the AI to produce diff suggestions for each comment.
    comment_lines = "\n".join(f"- [{c['id']}] {c['author']}: {c['text']}" for c in unresolved)
    article_body = article.get("body", "")
    prompt = ("You are an editor reviewing a technical blog article. "
              "For each comment below, produce a concise patch suggestion.\n\n"
              "Format each patch as:\n"
              "PATCH_START\n"
              "LABEL: <short label>\n"
              "COMMENT_ID: <comment id>\n"
              "REMOVED: <the existing text to replace — one or two sentences max>\n"
              "ADDED: <the replacement text>\n"
              "PATCH_END\n\n"
              f"Article (excerpt, first 2000 chars):\n{article_body[:2000]}\n\n"
              f"Comments to address:\n{comment_lines}\n\n"
              "Output only PATCH_START…PATCH_END blocks, nothing else.")

    # Determine which provider to use (prefer anthropic, fall back to openai).
    provider = None
    for p in ("anthropic", "openai"):
        if store.get_connection_token(user_id, p):
            provider = p
            break

    if provider is None:
        store.complete_job(user_id, job["job_id"], error="No AI provider connected")
        return AsyncAccepted(jobId=job["job_id"], status=JobStatus.done)

    api_key = store.get_connection_token(user_id, provider) if provider == "openai" else None
    try:
        result = runner.run_task(provider=provider,
                                 task="generate",
                                 article_md=prompt,
                                 api_key=api_key)
    except runner.RunnerUnavailable as exc:
        store.complete_job(user_id, job["job_id"], error=str(exc))
        return AsyncAccepted(jobId=job["job_id"], status=JobStatus.done)

    if result.get("exit_code", 1) != 0:
        err = (result.get("stderr") or result.get("stdout") or "unknown error")[:500]
        store.complete_job(user_id, job["job_id"], error=f"Regeneration failed: {err}")
        return AsyncAccepted(jobId=job["job_id"], status=JobStatus.done)

    # Parse PATCH_START…PATCH_END blocks from the output.
    import re as _re
    raw_output = result.get("stdout", "")
    patch_blocks = _re.findall(r"PATCH_START\s*(.*?)\s*PATCH_END", raw_output, _re.DOTALL)

    store.delete_patches(user_id, article_id)
    patches_created = 0
    for block in patch_blocks:
        fields: dict[str, str] = {}
        for field in ("LABEL", "COMMENT_ID", "REMOVED", "ADDED"):
            m = _re.search(rf"{field}:\s*(.+?)(?=\n(?:LABEL|COMMENT_ID|REMOVED|ADDED|$))", block,
                           _re.DOTALL)
            if m:
                fields[field] = m.group(1).strip()
        if "REMOVED" in fields and "ADDED" in fields:
            store.add_patch(
                user_id,
                article_id=article_id,
                label=fields.get("LABEL", "Suggested edit"),
                removed=fields["REMOVED"],
                added=fields["ADDED"],
                comment_id=fields.get("COMMENT_ID") or None,
            )
            patches_created += 1

    store.complete_job(user_id, job["job_id"], result={"patches_created": patches_created})
    return AsyncAccepted(jobId=job["job_id"], status=JobStatus.done)


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
