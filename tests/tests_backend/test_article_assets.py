from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
import backend.store as store


def _add_cover(
    article_id: str = "art_001",
    *,
    filename: str = "cover.png",
    content: bytes = b"png-cover",
    mime_type: str = "image/png",
) -> tuple[int, str]:
    asset_path = store.store_asset(
        store._backend.SEED_USER_ID,
        article_id,
        filename,
        content,
        mime_type,
    )
    asset_id = store._backend._con.execute(
        "SELECT id FROM article_assets WHERE article_id=? AND filename=?",
        (article_id, filename),
    ).fetchone()[0]
    store.upsert_remote_article_identity(
        store._backend.SEED_USER_ID,
        article_id,
        "hashnode",
        f"remote-{article_id}",
        cover_asset_id=asset_id,
    )
    return asset_id, asset_path


def _asset_url(article_id: str, asset_id: int) -> str:
    return f"/api/articles/{article_id}/assets/{asset_id}"


def test_owner_can_read_registered_cover_with_safe_headers(client: TestClient):
    asset_id, _ = _add_cover()
    with store._backend._con:
        store._backend._con.execute(
            "UPDATE article_assets SET filename=? WHERE id=?",
            ('../../unsafe\ncover".png', asset_id),
        )
    response = client.get(_asset_url("art_001", asset_id))

    assert response.status_code == 200
    assert response.content == b"png-cover"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, max-age=3600, must-revalidate"
    assert response.headers["vary"] == "Cookie"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["etag"].startswith('"')
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("inline;")
    assert ".." not in disposition
    assert "\n" not in disposition and "\r" not in disposition


def test_asset_read_requires_authentication(anon_client: TestClient):
    asset_id, _ = _add_cover()

    response = anon_client.get(_asset_url("art_001", asset_id))

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_other_user_and_missing_resources_share_non_leaking_404(client: TestClient):
    asset_id, _ = _add_cover()
    expected = {"detail": "Asset not found"}

    with TestClient(app) as other_user:
        registered = other_user.post(
            "/api/auth/register",
            json={"email": "asset-reader@example.com", "password": "password123"},
        )
        assert registered.status_code == 201
        unauthorized = other_user.get(_asset_url("art_001", asset_id))

    missing_article = client.get(_asset_url("art_missing", asset_id))
    missing_asset = client.get(_asset_url("art_001", asset_id + 1000))

    assert unauthorized.status_code == 404
    assert missing_article.status_code == 404
    assert missing_asset.status_code == 404
    assert unauthorized.json() == missing_article.json() == missing_asset.json() == expected


def test_missing_asset_file_uses_same_non_leaking_404(client: TestClient):
    asset_id, asset_path = _add_cover()
    (store._backend._blobs_dir / asset_path).unlink()

    response = client.get(_asset_url("art_001", asset_id))

    assert response.status_code == 404
    assert response.json() == {"detail": "Asset not found"}


def test_registered_traversal_path_cannot_escape_article_assets(
    client: TestClient,
):
    asset_id, _ = _add_cover()
    secret = store._backend._blobs_dir.parent / "asset-read-secret.png"
    secret.write_bytes(b"must-not-leak")
    try:
        with store._backend._con:
            store._backend._con.execute(
                "UPDATE article_assets SET asset_path=? WHERE id=?",
                ("../asset-read-secret.png", asset_id),
            )

        response = client.get(_asset_url("art_001", asset_id))

        assert response.status_code == 404
        assert response.json() == {"detail": "Asset not found"}
        assert b"must-not-leak" not in response.content
    finally:
        secret.unlink(missing_ok=True)


def test_unregistered_blob_cannot_be_requested(client: TestClient):
    assets_dir = store._backend._blobs_dir / "articles" / "art_001" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    unregistered = assets_dir / "unregistered.png"
    unregistered.write_bytes(b"not-registered")

    response = client.get(_asset_url("art_001", 999999))

    assert response.status_code == 404
    assert b"not-registered" not in response.content


def test_etag_revalidation_and_content_change(client: TestClient):
    asset_id, _ = _add_cover()
    url = _asset_url("art_001", asset_id)
    first = client.get(url)
    etag = first.headers["etag"]

    unchanged = client.get(url, headers={"If-None-Match": etag})
    assert unchanged.status_code == 304
    assert unchanged.content == b""
    assert unchanged.headers["etag"] == etag
    assert unchanged.headers["cache-control"].startswith("private")
    assert unchanged.headers["x-content-type-options"] == "nosniff"

    store.store_asset(
        store._backend.SEED_USER_ID,
        "art_001",
        "cover.png",
        b"changed-cover",
        "image/png",
    )
    changed = client.get(url, headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.content == b"changed-cover"
    assert changed.headers["etag"] != etag


def test_non_raster_asset_is_served_as_attachment(client: TestClient):
    asset_id, _ = _add_cover(
        filename="article.html",
        content=b"<script>alert(1)</script>",
        mime_type="text/html",
    )

    response = client.get(_asset_url("art_001", asset_id))

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_article_list_and_detail_expose_stable_local_cover_url(client: TestClient):
    asset_id, _ = _add_cover()
    expected = _asset_url("art_001", asset_id)

    summary = next(
        item for item in client.get("/api/articles").json()["items"]
        if item["id"] == "art_001"
    )
    detail = client.get("/api/articles/art_001").json()

    assert summary["previewImageUrl"] == expected
    assert detail["preview_image_url"] == expected
    assert client.get(expected).content == b"png-cover"


def test_article_without_cover_preserves_null_fallback_signal(client: TestClient):
    summary = next(
        item for item in client.get("/api/articles").json()["items"]
        if item["id"] == "art_002"
    )
    detail = client.get("/api/articles/art_002").json()

    assert summary["previewImageUrl"] is None
    assert detail["preview_image_url"] is None
