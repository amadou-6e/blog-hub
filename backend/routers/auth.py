"""Auth router — register, login, logout, me."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, field_validator

import bcrypt as _bcrypt

import backend.store as store


def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def _verify_password(password: str, password_hash: str) -> bool:
    return _bcrypt.checkpw(password.encode(), password_hash.encode())

router = APIRouter(prefix="/api/auth", tags=["auth"])

_COOKIE = "bloghub_session"
_REMEMBER_TTL = timedelta(days=30)
_SESSION_TTL  = timedelta(hours=1)
_HTTPS = os.environ.get("BLOGHUB_HTTPS", "").lower() == "true"


def _set_session_cookie(response: Response, token: str, remember: bool) -> None:
    max_age = int(_REMEMBER_TTL.total_seconds()) if remember else int(_SESSION_TTL.total_seconds())
    response.set_cookie(
        key=_COOKIE,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="strict",
        secure=_HTTPS,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=_COOKIE, path="/")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False


@router.post("/register", status_code=201)
def register(body: RegisterRequest, response: Response):
    if store.get_user_by_email(body.email):
        raise HTTPException(status_code=409,
                            detail="An account with this email already exists")
    password_hash = _hash_password(body.password)
    user = store.create_user(body.email, password_hash)

    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + _SESSION_TTL).isoformat()
    store.create_session(token, user["id"], expires_at, remember_me=False)
    _set_session_cookie(response, token, remember=False)

    return {"id": user["id"], "email": user["email"]}


@router.post("/login")
def login(body: LoginRequest, response: Response):
    user = store.get_user_by_email(body.email)
    _invalid = HTTPException(status_code=401, detail="Invalid email or password")

    if not user or not user["is_active"]:
        raise _invalid
    if not _verify_password(body.password, user["password_hash"]):
        raise _invalid

    token = secrets.token_urlsafe(32)
    ttl = _REMEMBER_TTL if body.remember_me else _SESSION_TTL
    expires_at = (datetime.now(timezone.utc) + ttl).isoformat()
    store.create_session(token, user["id"], expires_at, remember_me=body.remember_me)
    _set_session_cookie(response, token, remember=body.remember_me)

    return {"id": user["id"], "email": user["email"]}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(_COOKIE)
    if token:
        store.delete_session(token)
    _clear_session_cookie(response)
    return {"status": "logged_out"}


@router.get("/me")
def me(request: Request):
    token = request.cookies.get(_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    session = store.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired")
    user = store.get_user_by_id(session["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return {"id": user["id"], "email": user["email"], "created_at": user["created_at"]}
