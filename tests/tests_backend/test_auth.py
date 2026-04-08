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


class TestRegister:
    def test_register_creates_user_and_sets_cookie(self, client):
        r = client.post("/api/auth/register",
                        json={"email": "new@example.com", "password": "password123"})
        assert r.status_code == 201
        assert r.json()["email"] == "new@example.com"
        assert "bloghub_session" in r.cookies

    def test_register_duplicate_email_returns_409(self, client):
        client.post("/api/auth/register",
                    json={"email": "dup@example.com", "password": "password123"})
        r = client.post("/api/auth/register",
                        json={"email": "dup@example.com", "password": "password123"})
        assert r.status_code == 409

    def test_register_short_password_returns_422(self, client):
        r = client.post("/api/auth/register",
                        json={"email": "short@example.com", "password": "1234567"})
        assert r.status_code == 422


class TestLogin:
    def test_login_valid_credentials(self, client):
        client.post("/api/auth/register",
                    json={"email": "login@example.com", "password": "password123"})
        r = client.post("/api/auth/login",
                        json={"email": "login@example.com", "password": "password123",
                              "remember_me": False})
        assert r.status_code == 200
        assert "bloghub_session" in r.cookies

    def test_login_wrong_password_returns_401(self, client):
        client.post("/api/auth/register",
                    json={"email": "wp@example.com", "password": "password123"})
        r = client.post("/api/auth/login",
                        json={"email": "wp@example.com", "password": "wrongpassword",
                              "remember_me": False})
        assert r.status_code == 401
        assert r.json()["detail"] == "Invalid email or password"

    def test_login_unknown_email_returns_401(self, client):
        r = client.post("/api/auth/login",
                        json={"email": "ghost@example.com", "password": "password123",
                              "remember_me": False})
        assert r.status_code == 401
        assert r.json()["detail"] == "Invalid email or password"


class TestLogout:
    def test_logout_clears_session(self, client):
        client.post("/api/auth/register",
                    json={"email": "logout@example.com", "password": "password123"})
        r = client.post("/api/auth/logout")
        assert r.status_code == 200
        assert r.json()["status"] == "logged_out"


class TestMe:
    def test_me_returns_user_when_logged_in(self, client):
        client.post("/api/auth/register",
                    json={"email": "me@example.com", "password": "password123"})
        r = client.get("/api/auth/me")
        assert r.status_code == 200
        assert r.json()["email"] == "me@example.com"

    def test_me_returns_401_when_not_logged_in(self, anon_client):
        r = anon_client.get("/api/auth/me")
        assert r.status_code == 401


class TestMiddleware:
    def test_protected_route_returns_401_without_cookie(self, anon_client):
        r = anon_client.get("/api/articles")
        assert r.status_code == 401

    def test_protected_route_accessible_with_valid_session(self, client):
        client.post("/api/auth/register",
                    json={"email": "mw@example.com", "password": "password123"})
        r = client.get("/api/articles")
        assert r.status_code == 200

    def test_health_is_public(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_register_is_public(self, client):
        r = client.post("/api/auth/register",
                        json={"email": "pub@example.com", "password": "password123"})
        assert r.status_code == 201

    def test_login_is_public(self, client):
        client.post("/api/auth/register",
                    json={"email": "loginpub@example.com", "password": "password123"})
        r = client.post("/api/auth/login",
                        json={"email": "loginpub@example.com", "password": "password123",
                              "remember_me": False})
        assert r.status_code == 200
