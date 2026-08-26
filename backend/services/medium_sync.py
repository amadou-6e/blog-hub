"""Medium browser retrieval to local-workspace synchronization."""
from __future__ import annotations

from typing import Any, Callable

import backend.store as default_store
from backend.services.hashnode_sync import HashnodeSyncStore, sync_browser_records
from backend.services.image_ingest import IngestedImage, fetch_and_validate_image


def sync_medium_browser_records(
    user_id: str,
    retrieval: dict,
    *,
    store: HashnodeSyncStore = default_store,
    image_fetcher: Callable[[str], IngestedImage] = fetch_and_validate_image,
) -> dict[str, Any]:
    return sync_browser_records(
        user_id,
        retrieval,
        platform="medium",
        store=store,
        image_fetcher=image_fetcher,
    )
