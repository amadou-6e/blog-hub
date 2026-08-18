"""API models for local-versus-remote article reconciliation."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RemoteSnapshot(BaseModel):
    id: str
    article_id: str
    platform: str
    remote_id: str | None = None
    availability: str
    sync_state: str
    local_revision_id: str | None = None
    current_revision_id: str | None = None
    local_fingerprint: str
    remote_fingerprint: str | None = None
    title: str | None = None
    content: str | None = None
    canonical_url: str | None = None
    remote_url: str | None = None
    remote_status: str | None = None
    remote_updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    fetched_at: str


class ReconciliationListResponse(BaseModel):
    comparisons: list[RemoteSnapshot]


class ResolveRemoteConflictRequest(BaseModel):
    action: Literal["keep_local", "use_remote"]
    base_revision_id: str
