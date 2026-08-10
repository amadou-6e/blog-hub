"""Patches router — /api/articles/{article_id}/patches"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import backend.store as store

router = APIRouter(prefix="/api/articles", tags=["patches"])


class PatchOut(BaseModel):
    id: str
    articleId: str
    commentId: Optional[str]
    label: str
    removed: str
    added: str
    state: str
    createdAt: str
    baseRevisionId: Optional[str]


def _to_out(p: dict) -> PatchOut:
    return PatchOut(
        id=p["id"],
        articleId=p["article_id"],
        commentId=p["comment_id"],
        label=p["label"],
        removed=p["removed"],
        added=p["added"],
        state=p["state"],
        createdAt=p["created_at"],
        baseRevisionId=p.get("base_revision_id"),
    )


@router.get("/{article_id}/patches")
def list_patches(request: Request, article_id: str):
    user_id: str = request.state.user_id
    if store.get_article(user_id, article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"patches": [_to_out(p) for p in store.list_patches(user_id, article_id)]}


@router.post("/{article_id}/patches/{patch_id}/accept")
def accept_patch(request: Request, article_id: str, patch_id: str):
    user_id: str = request.state.user_id
    if store.get_article(user_id, article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    updated = store.set_patch_state(user_id, article_id, patch_id, "accepted")
    if updated is None:
        raise HTTPException(status_code=404, detail="Patch not found")
    return _to_out(updated)


@router.post("/{article_id}/patches/{patch_id}/reject")
def reject_patch(request: Request, article_id: str, patch_id: str):
    user_id: str = request.state.user_id
    if store.get_article(user_id, article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    updated = store.set_patch_state(user_id, article_id, patch_id, "rejected")
    if updated is None:
        raise HTTPException(status_code=404, detail="Patch not found")
    return _to_out(updated)
