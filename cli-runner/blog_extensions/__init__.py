"""Versioned extension contracts for browser-backed blog platforms."""

from .contracts import (
    ArticleInput,
    BlogExtension,
    BlogOperationsAdapter,
    BrowserLoginAdapter,
    Capability,
    ExtensionManifest,
    PUBLIC_OR_DESTRUCTIVE_CAPABILITIES,
    OperationRequest,
    OperationResult,
    OperationNotSupported,
    RemoteArticle,
)
from .registry import ExtensionRegistry, get_registry

__all__ = [
    "ArticleInput",
    "BlogExtension",
    "BlogOperationsAdapter",
    "BrowserLoginAdapter",
    "Capability",
    "ExtensionManifest",
    "PUBLIC_OR_DESTRUCTIVE_CAPABILITIES",
    "ExtensionRegistry",
    "OperationRequest",
    "OperationResult",
    "OperationNotSupported",
    "RemoteArticle",
    "get_registry",
]
