"""
ArticleStore Protocol — the contract every storage backend must satisfy.

Routers import from backend.store (the __init__), never from this file directly.
This file exists so mypy can verify that a new backend implements every method
before it ships.
"""
from __future__ import annotations

from typing import Protocol


class ArticleStore(Protocol):
    # ── Articles ─────────────────────────────────────────────────────────────

    def list_articles(
        self,
        q: str | None,
        gate: str | None,
        status: str | None,
        platform: str | None,
        page: int,
        page_size: int,
        sort_by: str,
        sort_dir: str,
    ) -> tuple[list[dict], int]: ...

    def get_article(self, article_id: str) -> dict | None: ...

    def create_article(
        self,
        title: str,
        source: str,
        source_platform: str | None,
        canonical_url: str | None,
    ) -> dict: ...

    def update_article_body(self, article_id: str, body: str, event: str) -> None: ...

    def delete_articles(self, ids: list[str], force: bool) -> list[str]: ...

    def find_article_by_canonical_url(self, canonical_url: str) -> dict | None: ...

    def find_article_by_title(self, title: str) -> dict | None: ...

    def merge_platform_into_article(
        self,
        article_id: str,
        platform: str,
        status: str,
        url: str | None,
        draft_id: str | None,
        event: str,
    ) -> dict: ...

    def apply_inspect_result(self, article_id: str, gate: str) -> None: ...

    def apply_push_result(
        self,
        article_id: str,
        platform: str,
        success: bool,
        url: str | None,
        error: str | None,
        label: str | None,
        draft_id: str | None,
    ) -> None: ...

    def set_destinations_pending(self, article_id: str, platforms: list[str]) -> None: ...

    # ── Connections ──────────────────────────────────────────────────────────

    def list_connections(self) -> list[dict]: ...

    def save_connection(
        self,
        conn_id: str,
        token: str,
        status: str,
        username: str | None,
        error: str | None,
    ) -> dict: ...

    def delete_connection(self, conn_id: str) -> None: ...

    def get_connection_token(self, conn_id: str) -> str | None: ...

    def count_connected(self) -> int: ...

    def create_oauth_state(self, conn_id: str) -> str: ...

    def consume_oauth_state(self, state: str, conn_id: str) -> bool: ...

    # ── Platforms ────────────────────────────────────────────────────────────

    def list_platforms(self) -> list[dict]: ...

    # ── Jobs ─────────────────────────────────────────────────────────────────

    def create_job(self, job_type: str, article_id: str) -> dict: ...

    def get_job(self, job_id: str) -> dict | None: ...

    def complete_job(
        self, job_id: str, result: dict | None, error: str | None
    ) -> None: ...

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def reset(self) -> None: ...
