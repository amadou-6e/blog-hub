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

_BLOG_HUB_DIR = Path(__file__).resolve().parents[2]  # backend/store/__init__.py → blog-hub/
_DB_PATH = os.environ.get("BLOGHUB_DB_PATH", str(_BLOG_HUB_DIR / "data" / "bloghub.db"))
_BLOBS_DIR = os.environ.get("BLOGHUB_BLOBS_DIR", str(_BLOG_HUB_DIR / "data" / "blobs"))
_backend = SQLiteStore(_DB_PATH, _BLOBS_DIR)

# ── Articles ──────────────────────────────────────────────────────────────────


def list_articles(user_id: str, *a, **kw):
    return _backend.list_articles(user_id, *a, **kw)


def get_article(user_id: str, *a, **kw):
    return _backend.get_article(user_id, *a, **kw)


def create_article(user_id: str, *a, **kw):
    return _backend.create_article(user_id, *a, **kw)


def update_article_body(user_id: str, *a, **kw):
    return _backend.update_article_body(user_id, *a, **kw)


def store_asset(user_id: str, *a, **kw):
    return _backend.store_asset(user_id, *a, **kw)


def update_article_title(user_id: str, *a, **kw):
    return _backend.update_article_title(user_id, *a, **kw)


def save_article_revision(user_id: str, *a, **kw):
    return _backend.save_article_revision(user_id, *a, **kw)


def get_current_article_revision(user_id: str, *a, **kw):
    return _backend.get_current_article_revision(user_id, *a, **kw)


def list_article_revisions(user_id: str, *a, **kw):
    return _backend.list_article_revisions(user_id, *a, **kw)


def get_article_revision(user_id: str, *a, **kw):
    return _backend.get_article_revision(user_id, *a, **kw)


def compare_article_revision(user_id: str, *a, **kw):
    return _backend.compare_article_revision(user_id, *a, **kw)


def restore_article_revision(user_id: str, *a, **kw):
    return _backend.restore_article_revision(user_id, *a, **kw)


def delete_articles(user_id: str, *a, **kw):
    return _backend.delete_articles(user_id, *a, **kw)


def find_article_by_canonical_url(user_id: str, *a, **kw):
    return _backend.find_article_by_canonical_url(user_id, *a, **kw)


def find_article_by_title(user_id: str, *a, **kw):
    return _backend.find_article_by_title(user_id, *a, **kw)


def merge_platform_into_article(user_id: str, *a, **kw):
    return _backend.merge_platform_into_article(user_id, *a, **kw)


def apply_inspect_result(user_id: str, *a, **kw):
    return _backend.apply_inspect_result(user_id, *a, **kw)


def apply_push_result(user_id: str, *a, **kw):
    return _backend.apply_push_result(user_id, *a, **kw)


def set_destinations_pending(user_id: str, *a, **kw):
    return _backend.set_destinations_pending(user_id, *a, **kw)


# ── Remote article identity ─────────────────────────────────────────────────


def get_remote_article_identity(user_id: str, *a, **kw):
    return _backend.get_remote_article_identity(user_id, *a, **kw)


def list_article_remote_identities(user_id: str, *a, **kw):
    return _backend.list_article_remote_identities(user_id, *a, **kw)


def upsert_remote_article_identity(user_id: str, *a, **kw):
    return _backend.upsert_remote_article_identity(user_id, *a, **kw)


# ── Connections ───────────────────────────────────────────────────────────────


def list_connections(user_id: str, *a, **kw):
    return _backend.list_connections(user_id, *a, **kw)


def save_connection(user_id: str, *a, **kw):
    return _backend.save_connection(user_id, *a, **kw)


def delete_connection(user_id: str, *a, **kw):
    return _backend.delete_connection(user_id, *a, **kw)


def get_connection_token(user_id: str, *a, **kw):
    return _backend.get_connection_token(user_id, *a, **kw)


def count_connected(user_id: str, *a, **kw):
    return _backend.count_connected(user_id, *a, **kw)


def create_connection_auth_flow(user_id: str, *a, **kw):
    return _backend.create_connection_auth_flow(user_id, *a, **kw)


def get_connection_auth_flow(user_id: str, *a, **kw):
    return _backend.get_connection_auth_flow(user_id, *a, **kw)


def get_latest_connection_auth_flow(user_id: str, *a, **kw):
    return _backend.get_latest_connection_auth_flow(user_id, *a, **kw)


def list_active_connection_auth_flows(user_id: str, *a, **kw):
    return _backend.list_active_connection_auth_flows(user_id, *a, **kw)


def update_connection_auth_flow(user_id: str, *a, **kw):
    return _backend.update_connection_auth_flow(user_id, *a, **kw)


def delete_connection_auth_flows(user_id: str, *a, **kw):
    return _backend.delete_connection_auth_flows(user_id, *a, **kw)


def expire_connection_auth_flows(*a, **kw):
    return _backend.expire_connection_auth_flows(*a, **kw)


def create_oauth_state(*a, **kw):
    return _backend.create_oauth_state(*a, **kw)


def consume_oauth_state(*a, **kw):
    return _backend.consume_oauth_state(*a, **kw)


# ── Platforms ─────────────────────────────────────────────────────────────────


def list_platforms(user_id: str, *a, **kw):
    return _backend.list_platforms(user_id, *a, **kw)


# ── Jobs ──────────────────────────────────────────────────────────────────────


def create_job(user_id: str, *a, **kw):
    return _backend.create_job(user_id, *a, **kw)


def get_job(user_id: str, *a, **kw):
    return _backend.get_job(user_id, *a, **kw)


def complete_job(user_id: str, *a, **kw):
    return _backend.complete_job(user_id, *a, **kw)


# ── Browser publishing ──────────────────────────────────────────────────────


def create_browser_publish_run(user_id: str, *a, **kw):
    return _backend.create_browser_publish_run(user_id, *a, **kw)


def get_browser_publish_run(user_id: str, *a, **kw):
    return _backend.get_browser_publish_run(user_id, *a, **kw)


def approve_browser_publish_run(user_id: str, *a, **kw):
    return _backend.approve_browser_publish_run(user_id, *a, **kw)


def complete_browser_publish_run(user_id: str, *a, **kw):
    return _backend.complete_browser_publish_run(user_id, *a, **kw)


def recover_browser_publish_runs():
    return _backend.recover_browser_publish_runs()


# ── Browser connections ────────────────────────────────────────────────────


def get_browser_connection(user_id: str, *a, **kw):
    return _backend.get_browser_connection(user_id, *a, **kw)


def start_browser_connection(user_id: str, *a, **kw):
    return _backend.start_browser_connection(user_id, *a, **kw)


def update_browser_connection(user_id: str, *a, **kw):
    return _backend.update_browser_connection(user_id, *a, **kw)


def delete_browser_connection(user_id: str, *a, **kw):
    return _backend.delete_browser_connection(user_id, *a, **kw)


# ── Agent sessions ───────────────────────────────────────────────────────────


def create_agent_session(user_id: str, *a, **kw):
    return _backend.create_agent_session(user_id, *a, **kw)


def list_agent_sessions(user_id: str, *a, **kw):
    return _backend.list_agent_sessions(user_id, *a, **kw)


def get_agent_session(user_id: str, *a, **kw):
    return _backend.get_agent_session(user_id, *a, **kw)


def add_agent_message(user_id: str, *a, **kw):
    return _backend.add_agent_message(user_id, *a, **kw)


def add_agent_event(user_id: str, *a, **kw):
    return _backend.add_agent_event(user_id, *a, **kw)


def record_agent_tool_call(user_id: str, *a, **kw):
    return _backend.record_agent_tool_call(user_id, *a, **kw)


def claim_agent_tool_call(user_id: str, *a, **kw):
    return _backend.claim_agent_tool_call(user_id, *a, **kw)


def complete_agent_tool_call(user_id: str, *a, **kw):
    return _backend.complete_agent_tool_call(user_id, *a, **kw)


def add_agent_checkpoint(user_id: str, *a, **kw):
    return _backend.add_agent_checkpoint(user_id, *a, **kw)


def request_agent_approval(user_id: str, *a, **kw):
    return _backend.request_agent_approval(user_id, *a, **kw)


def resolve_agent_approval(user_id: str, *a, **kw):
    return _backend.resolve_agent_approval(user_id, *a, **kw)


def add_agent_output(user_id: str, *a, **kw):
    return _backend.add_agent_output(user_id, *a, **kw)


def update_agent_session_status(user_id: str, *a, **kw):
    return _backend.update_agent_session_status(user_id, *a, **kw)


def resume_agent_session(user_id: str, *a, **kw):
    return _backend.resume_agent_session(user_id, *a, **kw)


def cancel_agent_session(user_id: str, *a, **kw):
    return _backend.cancel_agent_session(user_id, *a, **kw)


def archive_agent_session(user_id: str, *a, **kw):
    return _backend.archive_agent_session(user_id, *a, **kw)


def delete_agent_session(user_id: str, *a, **kw):
    return _backend.delete_agent_session(user_id, *a, **kw)


def export_agent_session(user_id: str, *a, **kw):
    return _backend.export_agent_session(user_id, *a, **kw)


def recover_agent_sessions():
    return _backend.recover_agent_sessions()


def cleanup_agent_sessions(*a, **kw):
    return _backend.cleanup_agent_sessions(*a, **kw)


# ── Comments ──────────────────────────────────────────────────────────────────


def list_comments(user_id: str, *a, **kw):
    return _backend.list_comments(user_id, *a, **kw)


def add_comment(user_id: str, *a, **kw):
    return _backend.add_comment(user_id, *a, **kw)


def update_comment(user_id: str, *a, **kw):
    return _backend.update_comment(user_id, *a, **kw)


def delete_comment(user_id: str, *a, **kw):
    return _backend.delete_comment(user_id, *a, **kw)


# ── Patches ───────────────────────────────────────────────────────────────────


def list_patches(user_id: str, *a, **kw):
    return _backend.list_patches(user_id, *a, **kw)


def get_patch(user_id: str, *a, **kw):
    return _backend.get_patch(user_id, *a, **kw)


def get_pending_agent_session_patch(user_id: str, *a, **kw):
    return _backend.get_pending_agent_session_patch(user_id, *a, **kw)


def add_patch(user_id: str, *a, **kw):
    return _backend.add_patch(user_id, *a, **kw)


def set_patch_state(user_id: str, *a, **kw):
    return _backend.set_patch_state(user_id, *a, **kw)


def delete_patches(user_id: str, *a, **kw):
    return _backend.delete_patches(user_id, *a, **kw)


# ── Chat log ──────────────────────────────────────────────────────────────────


def list_chat(user_id: str, *a, **kw):
    return _backend.list_chat(user_id, *a, **kw)


def add_chat_message(user_id: str, *a, **kw):
    return _backend.add_chat_message(user_id, *a, **kw)


# ── Auth: users ───────────────────────────────────────────────────────────────


def create_user(email: str, password_hash: str) -> dict:
    return _backend.create_user(email, password_hash)


def get_user_by_email(email: str) -> "dict | None":
    return _backend.get_user_by_email(email)


def get_user_by_id(user_id: str) -> "dict | None":
    return _backend.get_user_by_id(user_id)


# ── Auth: sessions ────────────────────────────────────────────────────────────


def create_session(token: str, user_id: str, expires_at: str,
                   remember_me: bool = False) -> None:
    return _backend.create_session(token, user_id, expires_at, remember_me)


def get_session(token: str) -> "dict | None":
    return _backend.get_session(token)


def delete_session(token: str) -> None:
    return _backend.delete_session(token)


def delete_expired_sessions() -> int:
    return _backend.delete_expired_sessions()


# ── Lifecycle ─────────────────────────────────────────────────────────────────


def schema_version() -> int:
    return _backend.schema_version


def create_backup(*a, **kw):
    return _backend.create_backup(*a, **kw)


def create_backup_if_due(*a, **kw):
    return _backend.create_backup_if_due(*a, **kw)


def close() -> None:
    return _backend.close()


def reset(*a, **kw):
    return _backend.reset(*a, **kw)
