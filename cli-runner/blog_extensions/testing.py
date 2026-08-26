"""Small contract-test helpers extension authors can use in their own suite."""
from __future__ import annotations

import json
from pathlib import Path

from .contracts import ArticleInput, BlogExtension, PROTOCOL_VERSION


def assert_extension_contract(extension: BlogExtension) -> None:
    assert extension.manifest.protocol_version == PROTOCOL_VERSION
    assert extension.login.platform == extension.manifest.platform
    assert extension.operations.platform == extension.manifest.platform
    assert extension.operations.capabilities == extension.manifest.capabilities
    assert extension.login.login_url.startswith("https://")


def article_from_fixture(path: str | Path) -> ArticleInput:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ArticleInput(
        title=payload["title"],
        body=payload["body"],
        remote_id=payload.get("remote_id"),
        subtitle=payload.get("subtitle"),
        cover_url=payload.get("cover_url"),
        canonical_url=payload.get("canonical_url"),
        tags=tuple(payload.get("tags", [])),
        metadata=payload.get("metadata", {}),
    )
