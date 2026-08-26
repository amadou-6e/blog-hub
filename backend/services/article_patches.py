"""Apply revision-bound article patches without overwriting newer work."""
from __future__ import annotations

import backend.store as store
from backend.store.article_revisions import RevisionConflict


class PatchConflict(ValueError):
    """Raised when a patch can no longer be applied to its recorded base."""


def apply_patch(
    *, user_id: str, article_id: str, patch_id: str, description: str | None = None
) -> tuple[dict, dict]:
    patch = store.get_patch(user_id, article_id, patch_id)
    if patch is None:
        raise KeyError(patch_id)
    if patch["state"] != "pending":
        current = store.get_current_article_revision(user_id, article_id)
        return patch, current

    current = store.get_current_article_revision(user_id, article_id)
    if current is None:
        raise KeyError(article_id)
    if current["id"] != patch["base_revision_id"]:
        raise RevisionConflict(current)

    if current["content"] == patch["removed"]:
        content = patch["added"]
    elif patch["removed"] in current["content"]:
        content = current["content"].replace(patch["removed"], patch["added"], 1)
    else:
        raise PatchConflict("The text targeted by this patch is no longer present")

    revision = store.save_article_revision(
        user_id,
        article_id,
        title=current["title"],
        content=content,
        expected_revision_id=current["id"],
        source="agent",
        description=description or f"Applied patch: {patch['label']}",
    )
    updated = store.set_patch_state(user_id, article_id, patch_id, "accepted")
    assert updated is not None
    return updated, revision


def apply_pending_session_patch(
    *, user_id: str, session_id: str
) -> tuple[dict | None, dict | None]:
    patch = store.get_pending_agent_session_patch(user_id, session_id)
    if patch is None:
        return None, None
    updated, revision = apply_patch(
        user_id=user_id,
        article_id=patch["article_id"],
        patch_id=patch["id"],
        description="Applied queued agent edit",
    )
    store.add_agent_event(
        user_id,
        session_id,
        "article_patch_applied",
        {"patch_id": updated["id"], "revision_id": revision["id"]},
    )
    return updated, revision
