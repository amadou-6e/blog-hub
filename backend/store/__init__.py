"""
backend.store — the single import point for all storage operations.

Routers do: import backend.store as store
They never reference a specific backend module.

To switch backends, change _backend below and nothing else.
"""
from __future__ import annotations

import os
from pathlib import Path

from backend.store.backends.sqlite import SQLiteStore

_DEFAULT_DB = Path(__file__).parent.parent.parent / "data" / "bloghub.db"
_DB_PATH = os.environ.get("BLOGHUB_DB_PATH", str(_DEFAULT_DB))
_backend = SQLiteStore(_DB_PATH)

# ── Articles ──────────────────────────────────────────────────────────────────


def list_articles(*a, **kw):
    return _backend.list_articles(*a, **kw)


def get_article(*a, **kw):
    return _backend.get_article(*a, **kw)


def create_article(*a, **kw):
    return _backend.create_article(*a, **kw)


def update_article_body(*a, **kw):
    return _backend.update_article_body(*a, **kw)


def update_article_title(*a, **kw):
    return _backend.update_article_title(*a, **kw)


def delete_articles(*a, **kw):
    return _backend.delete_articles(*a, **kw)


def find_article_by_canonical_url(*a, **kw):
    return _backend.find_article_by_canonical_url(*a, **kw)


def find_article_by_title(*a, **kw):
    return _backend.find_article_by_title(*a, **kw)


def merge_platform_into_article(*a, **kw):
    return _backend.merge_platform_into_article(*a, **kw)


def apply_inspect_result(*a, **kw):
    return _backend.apply_inspect_result(*a, **kw)


def apply_push_result(*a, **kw):
    return _backend.apply_push_result(*a, **kw)


def set_destinations_pending(*a, **kw):
    return _backend.set_destinations_pending(*a, **kw)


# ── Connections ───────────────────────────────────────────────────────────────


def list_connections(*a, **kw):
    return _backend.list_connections(*a, **kw)


def save_connection(*a, **kw):
    return _backend.save_connection(*a, **kw)


def delete_connection(*a, **kw):
    return _backend.delete_connection(*a, **kw)


def get_connection_token(*a, **kw):
    return _backend.get_connection_token(*a, **kw)


def count_connected(*a, **kw):
    return _backend.count_connected(*a, **kw)


def create_oauth_state(*a, **kw):
    return _backend.create_oauth_state(*a, **kw)


def consume_oauth_state(*a, **kw):
    return _backend.consume_oauth_state(*a, **kw)


# ── Platforms ─────────────────────────────────────────────────────────────────


def list_platforms(*a, **kw):
    return _backend.list_platforms(*a, **kw)


# ── Jobs ──────────────────────────────────────────────────────────────────────


def create_job(*a, **kw):
    return _backend.create_job(*a, **kw)


def get_job(*a, **kw):
    return _backend.get_job(*a, **kw)


def complete_job(*a, **kw):
    return _backend.complete_job(*a, **kw)


# ── Lifecycle ─────────────────────────────────────────────────────────────────


def reset(*a, **kw):
    return _backend.reset(*a, **kw)


# ── Comments ──────────────────────────────────────────────────────────────────


def list_comments(*a, **kw):
    return _backend.list_comments(*a, **kw)


def add_comment(*a, **kw):
    return _backend.add_comment(*a, **kw)


def update_comment(*a, **kw):
    return _backend.update_comment(*a, **kw)


def delete_comment(*a, **kw):
    return _backend.delete_comment(*a, **kw)


# ── Patches ───────────────────────────────────────────────────────────────────


def list_patches(*a, **kw):
    return _backend.list_patches(*a, **kw)


def add_patch(*a, **kw):
    return _backend.add_patch(*a, **kw)


def set_patch_state(*a, **kw):
    return _backend.set_patch_state(*a, **kw)


def delete_patches(*a, **kw):
    return _backend.delete_patches(*a, **kw)


# ── Chat log ──────────────────────────────────────────────────────────────────


def list_chat(*a, **kw):
    return _backend.list_chat(*a, **kw)


def add_chat_message(*a, **kw):
    return _backend.add_chat_message(*a, **kw)
