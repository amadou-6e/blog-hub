from fastapi import APIRouter, Request
from backend.schemas.overview import PlatformListResponse, PlatformConnection, Platform
import backend.store as store

router = APIRouter(prefix="/api/platforms", tags=["platforms"])


@router.get("", response_model=PlatformListResponse)
def list_platforms(request: Request):
    platforms = store.list_platforms(user_id=request.state.user_id)
    return PlatformListResponse(platforms=[
        PlatformConnection(
            id=Platform(p["id"]),
            connected=p["connected"],
            label=p["label"],
            username=p.get("username"),
        ) for p in platforms
    ])
