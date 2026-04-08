"""Tests for POST /api/articles/parse-upload."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient


def _make_zip(**entries: bytes | str) -> bytes:
    """Build an in-memory ZIP. Keys are filenames, values are content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            if isinstance(data, str):
                data = data.encode()
            zf.writestr(name, data)
    return buf.getvalue()


class TestParseUpload:

    # ── .md ──────────────────────────────────────────────────────────────────

    def test_md_returns_200(self, client: TestClient):
        r = client.post(
            "/api/articles/parse-upload",
            files={"file": ("article.md", b"# Hello\n\nContent", "text/markdown")},
        )
        assert r.status_code == 200

    def test_md_response_shape(self, client: TestClient):
        r = client.post(
            "/api/articles/parse-upload",
            files={
                "file": ("article.md", b"# Hello\n\nContent", "text/markdown")
            },
        ).json()
        assert r["filename"] == "article.md"
        assert r["content"] == "# Hello\n\nContent"
        assert r["content_type"] == "markdown"
        assert r["images"] == []

    def test_md_non_utf8_returns_422(self, client: TestClient):
        r = client.post(
            "/api/articles/parse-upload",
            files={"file": ("article.md", b"\xff\xfe bad bytes", "text/markdown")},
        )
        assert r.status_code == 422

    # ── .html ─────────────────────────────────────────────────────────────────

    def test_html_returns_200(self, client: TestClient):
        r = client.post(
            "/api/articles/parse-upload",
            files={"file": ("post.html", b"<h1>Hello</h1><p>World</p>", "text/html")},
        )
        assert r.status_code == 200

    def test_html_content_type_is_html(self, client: TestClient):
        r = client.post(
            "/api/articles/parse-upload",
            files={
                "file": ("post.html", b"<h1>Hi</h1>", "text/html")
            },
        ).json()
        assert r["content_type"] == "html"
        assert "<h1>" in r["content"]

    # ── .zip — happy paths ────────────────────────────────────────────────────

    def test_zip_with_md_returns_200(self, client: TestClient):
        data = _make_zip(**{"article.md": "# Zipped\n\nContent."})
        r = client.post(
            "/api/articles/parse-upload",
            files={"file": ("bundle.zip", data, "application/zip")},
        )
        assert r.status_code == 200

    def test_zip_with_md_extracts_content(self, client: TestClient):
        data = _make_zip(**{"article.md": "# Zipped Article\n\nText here."})
        r = client.post(
            "/api/articles/parse-upload",
            files={
                "file": ("bundle.zip", data, "application/zip")
            },
        ).json()
        assert r["content"] == "# Zipped Article\n\nText here."
        assert r["content_type"] == "markdown"
        assert r["filename"] == "article.md"

    def test_zip_with_md_and_images_lists_image_basenames(self, client: TestClient):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20  # minimal fake PNG header
        data = _make_zip(
            **{
                "article.md": "# Article\n\n![img](images/chart.png)",
                "images/chart.png": png,
                "logo.svg": b"<svg/>",
            })
        r = client.post(
            "/api/articles/parse-upload",
            files={
                "file": ("bundle.zip", data, "application/zip")
            },
        ).json()
        assert set(r["images"]) == {"chart.png", "logo.svg"}

    def test_zip_with_html_article(self, client: TestClient):
        data = _make_zip(**{"post.html": "<h1>Hello</h1><p>World</p>"})
        r = client.post(
            "/api/articles/parse-upload",
            files={
                "file": ("bundle.zip", data, "application/zip")
            },
        ).json()
        assert r["content_type"] == "html"
        assert "<h1>" in r["content"]

    # ── .zip — validation errors ──────────────────────────────────────────────

    def test_zip_no_article_file_returns_422(self, client: TestClient):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        data = _make_zip(**{"chart.png": png, "logo.svg": b"<svg/>"})
        r = client.post(
            "/api/articles/parse-upload",
            files={"file": ("bundle.zip", data, "application/zip")},
        )
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "no_article_found"

    def test_zip_disallowed_extension_returns_422(self, client: TestClient):
        data = _make_zip(**{
            "article.md": "# Good\n\nContent.",
            "malware.exe": b"MZ" + b"\x00" * 10,
        })
        r = client.post(
            "/api/articles/parse-upload",
            files={"file": ("bundle.zip", data, "application/zip")},
        )
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["error"] == "disallowed_file_types"
        assert any("malware.exe" in f for f in detail["rejected"])

    def test_zip_multiple_articles_returns_422(self, client: TestClient):
        data = _make_zip(**{
            "article1.md": "# First\n\nContent.",
            "article2.md": "# Second\n\nContent.",
        })
        r = client.post(
            "/api/articles/parse-upload",
            files={"file": ("bundle.zip", data, "application/zip")},
        )
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "multiple_articles"

    def test_zip_macos_metadata_is_skipped(self, client: TestClient):
        """__MACOSX entries must not count as disallowed or article files."""
        data = _make_zip(**{
            "article.md": "# Clean\n\nContent.",
            "__MACOSX/._article.md": b"\x00\x05\x16\x07",
        })
        r = client.post(
            "/api/articles/parse-upload",
            files={"file": ("bundle.zip", data, "application/zip")},
        )
        assert r.status_code == 200
        assert r.json()["content_type"] == "markdown"

    # ── unsupported extension ─────────────────────────────────────────────────

    def test_unsupported_extension_returns_415(self, client: TestClient):
        r = client.post(
            "/api/articles/parse-upload",
            files={"file": ("report.docx", b"PK fake", "application/octet-stream")},
        )
        assert r.status_code == 415

    # ── size limit ────────────────────────────────────────────────────────────

    def test_oversized_file_returns_413(self, client: TestClient):
        # 51 MB of zeroes — exceeds 50 MB limit
        big = b"\x00" * (51 * 1024 * 1024)
        r = client.post(
            "/api/articles/parse-upload",
            files={"file": ("big.md", big, "text/markdown")},
        )
        assert r.status_code == 413
