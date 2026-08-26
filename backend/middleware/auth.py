"""Auth middleware — enforces session cookie on all /api/* routes."""
from __future__ import annotations

import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

import backend.store as store
from backend.store.schema import SEED_USER_ID

_COOKIE = "bloghub_session"

_PUBLIC_PATHS = {
    "/health",
    "/api/auth/register",
    "/api/auth/login",
    "/api/dev/reset",
}


def _auth_disabled() -> bool:
    return os.environ.get("BLOGHUB_DISABLE_AUTH", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _is_public(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    if path.startswith("/screens/") or path.startswith("/generated-previews/"):
        return True
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _auth_disabled():
            request.state.user_id = SEED_USER_ID
            return await call_next(request)

        if _is_public(request.url.path):
            return await call_next(request)

        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        token = request.cookies.get(_COOKIE)
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )

        session = store.get_session(token)
        if not session:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Session expired or invalid"},
            )
            response.delete_cookie(key=_COOKIE, path="/")
            return response

        request.state.user_id = session["user_id"]
        return await call_next(request)
