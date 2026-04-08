"""Comments router — /api/articles/{article_id}/comments"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import backend.store as store

router = APIRouter(prefix="/api/articles", tags=["comments"])


class CommentOut(BaseModel):
    id: str
    articleId: str
    author: str
    text: str
    resolved: bool
    hasPatch: bool
    createdAt: str


class CreateCommentRequest(BaseModel):
    text: str
    author: Optional[str] = "anonymous"
    anchor: Optional[str] = None


class UpdateCommentRequest(BaseModel):
    resolved: Optional[bool] = None
    text: Optional[str] = None


def _to_out(c: dict) -> CommentOut:
    return CommentOut(
        id=c["id"],
        articleId=c["article_id"],
        author=c["author"],
        text=c["text"],
        resolved=c["resolved"],
        hasPatch=c["has_patch"],
        createdAt=c["created_at"],
    )


@router.get("/{article_id}/comments")
def list_comments(request: Request, article_id: str):
    user_id: str = request.state.user_id
    if store.get_article(user_id, article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"comments": [_to_out(c) for c in store.list_comments(user_id, article_id)]}


@router.post("/{article_id}/comments", status_code=201)
def create_comment(request: Request, article_id: str, body: CreateCommentRequest):
    user_id: str = request.state.user_id
    if store.get_article(user_id, article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    comment = store.add_comment(user_id, article_id, author=body.author, text=body.text, anchor=body.anchor)
    return _to_out(comment)


@router.patch("/{article_id}/comments/{comment_id}")
def update_comment(request: Request, article_id: str, comment_id: str, body: UpdateCommentRequest):
    user_id: str = request.state.user_id
    if store.get_article(user_id, article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    updated = store.update_comment(
        user_id,
        article_id,
        comment_id,
        resolved=body.resolved,
        text=body.text,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return _to_out(updated)


@router.delete("/{article_id}/comments/{comment_id}", status_code=204)
def delete_comment(request: Request, article_id: str, comment_id: str):
    user_id: str = request.state.user_id
    if store.get_article(user_id, article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    deleted = store.delete_comment(user_id, article_id, comment_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Comment not found")
