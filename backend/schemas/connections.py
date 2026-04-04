"""
Pydantic schemas — Connections
Covers both blog publishing platforms and AI providers.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ConnectionInfo(BaseModel):
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


class SaveTokenResponse(BaseModel):
    id: str
    status: str
    username: Optional[str] = None
    error_message: Optional[str] = None


class OAuthStartResponse(BaseModel):
    url: Optional[str] = None
    available: bool
