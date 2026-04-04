"""
Pydantic schemas — Overview screen
Mirror of contracts/overview.ts

Convention:
  - All timestamps: datetime (UTC), serialised to ISO-8601 strings.
  - Nullable fields: Optional[X] = None.
  - Client-derived fields are NOT present in these models.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# ─── Enums ────────────────────────────────────────────────────────────────────


class PlatformStatus(str, Enum):
    none = "none"
    draft = "draft"
    review = "review"
    ready = "ready"
    pending = "pending"
    error = "error"
    published = "published"


class GateStatus(str, Enum):
    pass_ = "pass"  # 'pass' is reserved in Python, use pass_ internally
    warn = "warn"
    fail = "fail"
    pending = "pending"

    # Allow JSON round-trip with the wire value "pass"
    @classmethod
    def _missing_(cls, value: object):
        if value == "pass":
            return cls.pass_
        return None


class Platform(str, Enum):
    medium = "medium"
    hashnode = "hashnode"
    devto = "devto"


class JobType(str, Enum):
    inspect = "inspect"
    push = "push"
    generate = "generate"


class JobStatus(str, Enum):
    running = "running"
    done = "done"
    error = "error"


# ─── Read models (backend → UI) ───────────────────────────────────────────────


class PlatformSummary(BaseModel):
    status: PlatformStatus
    label: str
    url: Optional[str] = None
    error: Optional[str] = None


class TimelineEvent(BaseModel):
    timestamp: datetime
    event: str


class ArticleSummary(BaseModel):
    id: str
    title: str
    updated_at: datetime = Field(alias="updatedAt")
    word_count: int = Field(alias="wordCount")
    gate: GateStatus
    destinations: dict[Platform, PlatformSummary]
    recent_timeline: list[TimelineEvent] = Field(
        alias="recentTimeline",
        description="Last 5 events, newest first.",
    )

    model_config = {"populate_by_name": True}


class ArticleListResponse(BaseModel):
    items: list[ArticleSummary]
    total: int
    page: int
    page_size: int = Field(alias="pageSize")

    model_config = {"populate_by_name": True}


# ─── Query params ─────────────────────────────────────────────────────────────


class ArticleListQuery(BaseModel):
    q: Optional[str] = None
    gate: Optional[GateStatus] = None
    status: Optional[PlatformStatus] = None
    platform: Optional[Platform] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100, alias="pageSize")
    sort_by: str = Field(default="updatedAt", alias="sortBy")
    sort_dir: str = Field(default="desc", alias="sortDir")

    model_config = {"populate_by_name": True}


# ─── Write operations (UI → backend) ──────────────────────────────────────────


class CreateArticleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)


class CreateArticleResponse(BaseModel):
    id: str
    title: str
    created_at: datetime = Field(alias="createdAt")

    model_config = {"populate_by_name": True}


class DeleteArticleRequest(BaseModel):
    ids: list[str] = Field(min_length=1)
    force: bool = False


# ─── Job models ───────────────────────────────────────────────────────────────


class JobResponse(BaseModel):
    job_id: str = Field(alias="jobId")
    type: JobType
    status: JobStatus
    article_id: str = Field(alias="articleId")
    result: Optional[dict] = None
    error: Optional[str] = None

    model_config = {"populate_by_name": True}


class AsyncAccepted(BaseModel):
    job_id: str = Field(alias="jobId")
    status: JobStatus

    model_config = {"populate_by_name": True}


# ─── Platform connection ───────────────────────────────────────────────────────


class PlatformConnection(BaseModel):
    id: Platform
    connected: bool
    label: str
    username: Optional[str] = None


class PlatformListResponse(BaseModel):
    platforms: list[PlatformConnection]
