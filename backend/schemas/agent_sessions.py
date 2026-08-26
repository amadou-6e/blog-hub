"""Request models for durable agent sessions."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CreateAgentSessionRequest(CamelModel):
    provider: str = Field(min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    article_id: str | None = None
    workspace_id: str = Field(default="default", min_length=1, max_length=120)
    title: str | None = Field(default=None, max_length=240)
    metadata: dict[str, Any] = Field(default_factory=dict)
    expires_in_days: int = Field(default=30, ge=0, le=365)


class AddMessageRequest(CamelModel):
    role: str
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatTurnRequest(CamelModel):
    content: str = Field(min_length=1, max_length=20_000)
    article_revision_id: str = Field(min_length=1)


class CloseAgentSessionRequest(CamelModel):
    article_revision_id: str = Field(min_length=1)


class RecordToolCallRequest(CamelModel):
    idempotency_key: str = Field(min_length=1, max_length=240)
    name: str = Field(min_length=1, max_length=160)
    arguments: dict[str, Any] = Field(default_factory=dict)


class CompleteToolCallRequest(CamelModel):
    result: Any = None
    error: str | None = None


class AddCheckpointRequest(BaseModel):
    state: dict[str, Any]


class RequestApprovalRequest(CamelModel):
    request: dict[str, Any]
    tool_call_id: str | None = None


class ResolveApprovalRequest(BaseModel):
    approved: bool
    response: dict[str, Any] = Field(default_factory=dict)


class AddOutputRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=80)
    reference: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
