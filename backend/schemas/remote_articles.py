"""API-facing models for durable remote article identity metadata."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RemoteSyncStatus(str, Enum):
    succeeded = "succeeded"
    partial = "partial"
    failed = "failed"


class RemoteArticleIdentity(BaseModel):
    article_id: str = Field(alias="articleId")
    platform: str
    remote_id: str = Field(alias="remoteId")
    remote_content_fingerprint: str | None = Field(
        default=None, alias="remoteContentFingerprint",
    )
    subtitle: str | None = None
    cover_asset_id: int | None = Field(default=None, alias="coverAssetId")
    last_sync_status: RemoteSyncStatus | None = Field(
        default=None, alias="lastSyncStatus",
    )
    last_sync_result: dict[str, Any] | None = Field(
        default=None, alias="lastSyncResult",
    )
    last_sync_error: str | None = Field(default=None, alias="lastSyncError")
    remote_created_at: datetime | None = Field(default=None, alias="remoteCreatedAt")
    remote_updated_at: datetime | None = Field(default=None, alias="remoteUpdatedAt")
    last_sync_started_at: datetime | None = Field(
        default=None, alias="lastSyncStartedAt",
    )
    last_synced_at: datetime | None = Field(default=None, alias="lastSyncedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)
