"""Live article preview endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import backend.store as store
from backend.schemas.previews import (
    PreviewArtifact,
    PreviewCapabilities,
    PreviewRenderRequest,
    PreviewSource,
)
from backend.services.platform_previews.engine import preview_engine, working_copy_fingerprint


router = APIRouter(prefix="/api/articles/{article_id}/previews", tags=["previews"])


@router.get("/capabilities", response_model=list[PreviewCapabilities])
def preview_capabilities(article_id: str, request: Request):
    if store.get_article(request.state.user_id, article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return preview_engine.capabilities()


@router.post("/render", response_model=PreviewArtifact)
def render_preview(article_id: str, body: PreviewRenderRequest, request: Request):
    user_id = request.state.user_id
    article = store.get_article(user_id, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    current = store.get_current_article_revision(user_id, article_id)
    fingerprint = working_copy_fingerprint(body.title, body.content)
    matches_current = bool(
        current
        and body.base_revision_id == current["id"]
        and body.title == current["title"]
        and body.content == current["content"]
    )
    source = PreviewSource(
        article_id=article_id,
        revision_id=current["id"] if matches_current else None,
        revision_number=current["revision_number"] if matches_current else None,
        working_copy_fingerprint=None if matches_current else fingerprint,
    )
    try:
        return preview_engine.render(
            body,
            source=source,
            asset_base_url=f"/api/articles/{article_id}/assets/by-filename",
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=501,
            detail={"code": "preview_not_supported", "platform": str(exc.args[0])},
        ) from exc

