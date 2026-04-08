"""Tests for auth store methods — users and sessions."""
import os
os.environ.setdefault("BLOGHUB_DB_PATH", ":memory:")

import pytest
from datetime import datetime, timezone, timedelta
import backend.store as store


class TestCreateUser:
    def test_creates_user_with_hashed_password(self):
        user = store.create_user("alice@example.com", "hashed_pw")
        assert user["email"] == "alice@example.com"
        assert user["password_hash"] == "hashed_pw"
        assert "id" in user
        assert user["is_active"] is True

    def test_duplicate_email_raises(self):
        store.create_user("bob@example.com", "hash1")
        with pytest.raises(Exception):
            store.create_user("bob@example.com", "hash2")


class TestGetUserByEmail:
    def test_returns_user(self):
        store.create_user("carol@example.com", "h")
        user = store.get_user_by_email("carol@example.com")
        assert user is not None
        assert user["email"] == "carol@example.com"

    def test_returns_none_for_unknown(self):
        assert store.get_user_by_email("nobody@example.com") is None


class TestSessions:
    def test_create_and_get_session(self):
        user = store.create_user("dave@example.com", "h")
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        store.create_session("tok123", user["id"], expires, remember_me=False)
        session = store.get_session("tok123")
        assert session is not None
        assert session["user_id"] == user["id"]

    def test_get_expired_session_returns_none(self):
        user = store.create_user("eve@example.com", "h")
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        store.create_session("oldtok", user["id"], past, remember_me=False)
        assert store.get_session("oldtok") is None

    def test_delete_session(self):
        user = store.create_user("frank@example.com", "h")
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        store.create_session("deltok", user["id"], expires, remember_me=False)
        store.delete_session("deltok")
        assert store.get_session("deltok") is None

    def test_delete_expired_sessions(self):
        user = store.create_user("grace@example.com", "h")
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        store.create_session("expired1", user["id"], past, remember_me=False)
        store.create_session("valid1", user["id"], future, remember_me=False)
        deleted = store.delete_expired_sessions()
        assert deleted == 1
        assert store.get_session("valid1") is not None
