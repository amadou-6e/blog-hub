"""Public, versioned interfaces implemented by BlogHub browser extensions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, NotRequired, TypedDict


PROTOCOL_VERSION = 1


class Capability(StrEnum):
    LIST_ARTICLES = "list_articles"
    GET_ARTICLE = "get_article"
    CREATE_DRAFT = "create_draft"
    UPDATE_ARTICLE = "update_article"
    PUBLISH = "publish"
    UNPUBLISH = "unpublish"
    DELETE = "delete"


PUBLIC_OR_DESTRUCTIVE_CAPABILITIES = frozenset({
    Capability.UPDATE_ARTICLE,
    Capability.PUBLISH,
    Capability.UNPUBLISH,
    Capability.DELETE,
})


@dataclass(frozen=True)
class ArticleInput:
    """Normalized article data passed to an operations adapter."""

    title: str
    body: str
    remote_id: str | None = None
    subtitle: str | None = None
    cover_url: str | None = None
    canonical_url: str | None = None
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationRequest:
    """Normalized operation input for both reads and writes."""

    article: ArticleInput | None = None
    remote_id: str | None = None
    cursor: str | None = None
    limit: int = 50


class RemoteArticle(TypedDict):
    remote_id: str
    title: str
    body: str
    status: str
    subtitle: NotRequired[str | None]
    cover_url: NotRequired[str | None]
    canonical_url: NotRequired[str | None]
    tags: NotRequired[list[str]]
    created_at: NotRequired[str | None]
    updated_at: NotRequired[str | None]
    published_at: NotRequired[str | None]
    fingerprint: NotRequired[str | None]
    metadata: NotRequired[dict[str, Any]]


class OperationResult(TypedDict):
    success: bool
    status: NotRequired[str]
    remote_id: NotRequired[str | None]
    url: NotRequired[str | None]
    article: NotRequired[RemoteArticle]
    articles: NotRequired[list[RemoteArticle]]
    next_cursor: NotRequired[str | None]
    error: NotRequired[str]
    diagnostics: NotRequired[dict[str, Any]]


@dataclass(frozen=True)
class ExtensionManifest:
    protocol_version: int
    extension_id: str
    platform: str
    display_name: str
    version: str
    login_entrypoint: str
    operations_entrypoint: str
    capabilities: frozenset[Capability]
    source: Path


class OperationNotSupported(RuntimeError):
    def __init__(self, platform: str, operation: str) -> None:
        super().__init__(f"{platform} does not support browser operation: {operation}")
        self.platform = platform
        self.operation = operation


class BrowserLoginAdapter(ABC):
    """Platform-specific login navigation and persisted-profile verification."""

    platform: str
    login_url: str

    @abstractmethod
    def verify_profile(self, profile_dir: Path) -> dict[str, Any]:
        """Return an authentication result without exposing session material."""


class BlogOperationsAdapter(ABC):
    """Deterministic Playwright operations against an authenticated page."""

    platform: str
    capabilities: frozenset[Capability] = frozenset()

    def supports(self, operation: str | Capability) -> bool:
        try:
            capability = Capability(operation)
        except ValueError:
            return False
        return capability in self.capabilities

    @abstractmethod
    def execute(
        self,
        page: Any,
        operation: Capability,
        request: OperationRequest,
    ) -> OperationResult:
        """Execute one declared capability using only the supplied browser page."""


@dataclass(frozen=True)
class BlogExtension:
    manifest: ExtensionManifest
    login: BrowserLoginAdapter
    operations: BlogOperationsAdapter

    def descriptor(self) -> dict[str, Any]:
        return {
            "id": self.manifest.extension_id,
            "platform": self.manifest.platform,
            "display_name": self.manifest.display_name,
            "version": self.manifest.version,
            "protocol_version": self.manifest.protocol_version,
            "capabilities": sorted(capability.value for capability in self.manifest.capabilities),
        }
