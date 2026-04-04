from fastapi import APIRouter
from backend.schemas.overview import PlatformListResponse, PlatformConnection, Platform
import backend.store.memory as store

router = APIRouter(prefix="/api/platforms", tags=["platforms"])


@router.get("", response_model=PlatformListResponse)
def list_platforms():
    platforms = store.list_platforms()
    return PlatformListResponse(platforms=[
        PlatformConnection(
            id=Platform(p["id"]),
            connected=p["connected"],
            label=p["label"],
            username=p.get("username"),
        ) for p in platforms
    ])
