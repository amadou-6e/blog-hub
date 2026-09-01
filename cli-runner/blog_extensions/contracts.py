"""Public, versioned interfaces implemented by BlogHub browser extensions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, NotRequired, TypedDict
from urllib.parse import urlsplit


PROTOCOL_VERSION = 1
HEALTH_PROTOCOL_VERSION = 1


class ConnectionHealthStatus(StrEnum):
    CONNECTED = "connected"
    VERIFICATION_STALE = "verification_stale"
    REAUTHENTICATION_REQUIRED = "reauthentication_required"
    TEMPORARILY_BLOCKED = "temporarily_blocked"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


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
    platform: str
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
    connection_health: NotRequired[ConnectionHealthEvidence]


class ConnectionHealthEvidence(TypedDict):
    protocol_version: int
    status: str
    reason: str
    source: str
    authoritative: bool
    retry_after_seconds: NotRequired[int]
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

    def session_domains(self) -> tuple[str, ...]:
        """Domains whose cookies represent this platform's own login."""
        hostname = urlsplit(self.login_url).hostname
        return (hostname,) if hostname else ()

    @abstractmethod
    def verify_profile(self, profile_dir: Path) -> dict[str, Any]:
        """Return an authentication result without exposing session material."""

    def verify_live_session(self, probe: dict[str, Any]) -> dict[str, Any]:
        """Interpret sanitized evidence from a running browser session."""
        return {"authenticated": False, "status": "login_required"}

    def profile_health(self, profile_dir: Path) -> ConnectionHealthEvidence:
        """Normalize stored credential hints without treating them as live proof."""
        result = self.verify_profile(profile_dir)
        return _authentication_health(
            result, source="stored_profile", authoritative=False,
        )

    def live_health(self, probe: dict[str, Any]) -> ConnectionHealthEvidence:
        """Normalize a live browser probe into the shared health protocol."""
        return _authentication_health(
            self.verify_live_session(probe),
            source="live_browser_probe",
            authoritative=True,
        )


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

    def operation_health(
        self, operation: Capability, result: OperationResult,
    ) -> ConnectionHealthEvidence:
        """Classify sanitized operation output without platform-specific branching."""
        if result.get("success"):
            return _health_evidence(
                ConnectionHealthStatus.CONNECTED,
                reason="remote_operation_succeeded",
                source="remote_operation",
                authoritative=True,
                diagnostics={"operation": operation.value},
            )

        searchable = " ".join(_diagnostic_strings({
            "error": result.get("error"),
            "diagnostics": result.get("diagnostics"),
        })).lower()
        diagnostics: dict[str, Any] = {"operation": operation.value}
        http_status = _find_scalar(result.get("diagnostics"), "http_status")
        retry_after = _find_scalar(
            result.get("diagnostics"), "retry_after_seconds",
        )
        if isinstance(http_status, int):
            diagnostics["http_status"] = http_status
        if any(token in searchable for token in (
            "login_required", "not authenticated", "authentication required",
            "sign in", "signin",
        )):
            status = ConnectionHealthStatus.REAUTHENTICATION_REQUIRED
            reason = "remote_authentication_required"
        elif any(token in searchable for token in ("rate limit", "too many requests", "429")):
            status = ConnectionHealthStatus.RATE_LIMITED
            reason = "remote_rate_limited"
        elif any(token in searchable for token in ("captcha", "challenge", "temporarily blocked")):
            status = ConnectionHealthStatus.TEMPORARILY_BLOCKED
            reason = "remote_challenge"
            diagnostics["challenge"] = True
        elif any(token in searchable for token in ("unavailable", "timeout", "timed out", "503")):
            status = ConnectionHealthStatus.UNAVAILABLE
            reason = "remote_unavailable"
        else:
            status = ConnectionHealthStatus.UNKNOWN
            reason = "remote_operation_failed"
        return _health_evidence(
            status,
            reason=reason,
            source="remote_operation",
            authoritative=True,
            diagnostics=diagnostics,
            retry_after_seconds=(
                retry_after if isinstance(retry_after, int) else None
            ),
        )


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
            "health_protocol_version": HEALTH_PROTOCOL_VERSION,
            "capabilities": sorted(capability.value for capability in self.manifest.capabilities),
        }


def _health_evidence(
    status: ConnectionHealthStatus,
    *,
    reason: str,
    source: str,
    authoritative: bool,
    diagnostics: dict[str, Any] | None = None,
    retry_after_seconds: int | None = None,
) -> ConnectionHealthEvidence:
    evidence: ConnectionHealthEvidence = {
        "protocol_version": HEALTH_PROTOCOL_VERSION,
        "status": status.value,
        "reason": reason,
        "source": source,
        "authoritative": authoritative,
    }
    if diagnostics:
        evidence["diagnostics"] = diagnostics
    if retry_after_seconds is not None:
        evidence["retry_after_seconds"] = retry_after_seconds
    return evidence


def _authentication_health(
    result: Mapping[str, Any], *, source: str, authoritative: bool,
) -> ConnectionHealthEvidence:
    authenticated = result.get("authenticated")
    if authenticated is True:
        status = ConnectionHealthStatus.CONNECTED
        reason = "authentication_verified"
    elif authenticated is False:
        status = ConnectionHealthStatus.REAUTHENTICATION_REQUIRED
        reason = "authentication_required"
    else:
        status = ConnectionHealthStatus.UNKNOWN
        reason = "authentication_unknown"
    return _health_evidence(
        status, reason=reason, source=source, authoritative=authoritative,
    )


def _diagnostic_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [
            item
            for nested in value.values()
            for item in _diagnostic_strings(nested)
        ]
    if isinstance(value, (list, tuple)):
        return [item for nested in value for item in _diagnostic_strings(nested)]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [str(value)]
    return []


def _find_scalar(value: object, key: str) -> object | None:
    if isinstance(value, Mapping):
        if key in value:
            return value[key]
        for nested in value.values():
            found = _find_scalar(nested, key)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found = _find_scalar(nested, key)
            if found is not None:
                return found
    return None
