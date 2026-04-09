"""Comments router — /api/articles/{article_id}/comments"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import backend.store as store

router = APIRouter(prefix="/api/articles", tags=["comments"])

class CommentOut(BaseModel):
    id: str
    articleId: str
    author: str
    text: str
    anchor: Optional[str] = None
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
        anchor=c.get("anchor"),
        resolved=c["resolved"],
        hasPatch=c["has_patch"],
        createdAt=c["created_at"],
    )


@router.get("/{article_id}/comments")
def list_comments(article_id: str):
    if store.get_article(article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"comments": [_to_out(c) for c in store.list_comments(article_id)]}


@router.post("/{article_id}/comments", status_code=201)
def create_comment(article_id: str, body: CreateCommentRequest):
    if store.get_article(article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    comment = store.add_comment(
        article_id,
        author=body.author or "anonymous",
        text=body.text,
        anchor=body.anchor,
    )
    return _to_out(comment)


@router.patch("/{article_id}/comments/{comment_id}")
def update_comment(article_id: str, comment_id: str, body: UpdateCommentRequest):
    if store.get_article(article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    updated = store.update_comment(
        article_id, comment_id,
        resolved=body.resolved,
        text=body.text,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return _to_out(updated)


@router.delete("/{article_id}/comments/{comment_id}", status_code=204)
def delete_comment(article_id: str, comment_id: str):
    if store.get_article(article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    deleted = store.delete_comment(article_id, comment_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Comment not found")
