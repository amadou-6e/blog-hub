"""
Pydantic schemas — Connections
Covers both blog publishing platforms and AI providers.

Field naming: API responses use camelCase (alias_generator) to match the
swagger spec. Internal code uses snake_case attribute names.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class ConnectionInfo(_CamelModel):
    id: str
    label: str
    type: str  # "blog" | "ai"
    auth_method: str  # "token" | "oauth_or_token"
    status: str  # "disconnected" | "connected" | "error"
    username: Optional[str] = None
    connected_at: Optional[datetime] = None
    error_message: Optional[str] = None


class ConnectionListResponse(BaseModel):
    connections: list[ConnectionInfo]


class SaveTokenRequest(BaseModel):
    token: str = Field(min_length=1)


class SaveTokenResponse(_CamelModel):
    id: str
    status: str
    username: Optional[str] = None
    error_message: Optional[str] = None


class OAuthStartResponse(BaseModel):
    available: bool
    url: Optional[str] = None
    flow: Optional[str] = None  # "oauth_popup" | "cli_browser" | "device_code"
    poll_url: Optional[str] = None  # set when flow == "cli_browser" or "device_code"
    device_code: Optional[str] = None  # set when flow == "device_code"


class AgentAuthFlowResponse(_CamelModel):
    flow_id: str
    provider: str
    flow_type: str  # "browser_callback" | "device_code"
    status: str
    authorization_url: Optional[str] = None
    device_code: Optional[str] = None
    username: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    recovery: Optional[str] = None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class AgentAuthCallbackRequest(_CamelModel):
    callback_url: str = Field(min_length=1, max_length=4096)


class ActiveAgentAuthFlowsResponse(_CamelModel):
    flows: list[AgentAuthFlowResponse]


class TestConnectionResponse(BaseModel):
    ok: bool
    detail: str


# ── Draft / import schemas ────────────────────────────────────────────────────


class DraftSummary(BaseModel):
    id: str
    title: str
    word_count: int
    updated_at: str
    status: str  # "draft" | "published"
    snippet: str = ""
    cover_image: Optional[str] = None


class DraftListResponse(BaseModel):
    platform: str
    drafts: list[DraftSummary]
    total: int
    page: int
    per_page: int
    has_more: bool


class DraftContent(BaseModel):
    id: str
    title: str
    word_count: int
    updated_at: str
    status: str
    body: str
    canonical_url: Optional[str] = None
    cover_image: Optional[str] = None


class HashnodeSyncSourceError(_CamelModel):
    source: str
    error: str


class HashnodeSyncArticleResult(_CamelModel):
    remote_id: str
    article_id: Optional[str] = None
    status: str
    action: str
    revision_created: bool
    image_status: str
    error: Optional[str] = None


class HashnodeSyncResponse(_CamelModel):
    status: str
    started_at: datetime
    completed_at: datetime
    fetched: int
    imported: int
    updated: int
    metadata_updated: int
    unchanged: int
    failed: int
    images_downloaded: int
    images_failed: int
    source_errors: list[HashnodeSyncSourceError]
    articles: list[HashnodeSyncArticleResult]
