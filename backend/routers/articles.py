from fastapi import APIRouter, HTTPException, Query
from typing import Optional

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
import backend.store.memory as store
from backend.services.push import push_article_to_platforms

router = APIRouter(prefix="/api/articles", tags=["articles"])


def _article_to_schema(a: dict) -> ArticleSummary:
    return ArticleSummary(
        id=a["id"],
        title=a["title"],
        updatedAt=a["updated_at"],
        wordCount=a["word_count"],
        gate=a["gate"],
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
