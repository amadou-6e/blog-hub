"""API contracts for local-versus-remote reconciliation."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ReconciliationObservation(_Model):
    id: str
    article_id: str
    platform: str
    remote_id: str
    local_revision_id: str | None = None
    current_revision_id: str | None = None
    baseline_fingerprint: str | None = None
    local_fingerprint: str
    remote_fingerprint: str | None = None
    availability: str
    sync_state: str
    remote_title: str | None = None
    remote_content: str | None = None
    canonical_url: str | None = None
    remote_url: str | None = None
    remote_status: str | None = None
    remote_updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    observed_at: str


class ReconciliationListResponse(_Model):
    comparisons: list[ReconciliationObservation]


class ResolveReconciliationRequest(_Model):
    action: Literal["keep_local", "use_remote"]
    base_revision_id: str
