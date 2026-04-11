"""
tests/tests_ui/utils/remote.py
──────────────────────────────
Helpers for fetching remote assets (images, HTML pages) and persisting them
to outputs/remote_dumps/ so tests can place them side-by-side with local
screenshots for human visual comparison.

All outputs land under:
    tests/tests_ui/outputs/remote_dumps/images/<name>.{ext}
    tests/tests_ui/outputs/remote_dumps/html/<name>.html

Usage
-----
from tests.tests_ui.utils.remote import fetch_remote_image, fetch_remote_html

img_path = fetch_remote_image(
    "https://raw.githubusercontent.com/.../title.png",
    "hashnode_cover_title",
)
html_path = fetch_remote_html(
    "https://hashnode.com/some-article",
    "hashnode_article_page",
)

Both return the saved Path, or None if the fetch fails (so callers can skip
instead of hard-fail on CDN downtime).
"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional

import requests

_DUMPS_ROOT = Path(__file__).resolve().parents[1] / "outputs" / "remote_dumps"
_TIMEOUT = 15  # seconds


def fetch_remote_image(url: str, name: str, *, ext: str | None = None) -> Optional[Path]:
    """Download a remote image and save it to outputs/remote_dumps/images/.

    Parameters
    ----------
    url:  The full URL of the image to fetch.
    name: Base filename (without extension) — e.g. "hashnode_cover_title".
    ext:  Optional explicit extension override (e.g. "png").
          If omitted, guessed from the Content-Type header or URL suffix.

    Returns the saved Path, or None if the fetch fails or returns non-200.
    """
    out_dir = _DUMPS_ROOT / "images"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        resp = requests.get(url, timeout=_TIMEOUT, stream=True)
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    if ext is None:
        ct = resp.headers.get("Content-Type", "")
        guessed = mimetypes.guess_extension(ct.split(";")[0].strip()) or ""
        ext = guessed.lstrip(".") or _ext_from_url(url) or "png"

    path = out_dir / f"{name}.{ext}"
    path.write_bytes(resp.content)
    return path


def fetch_remote_html(url: str, name: str) -> Optional[Path]:
    """Fetch a remote HTML page and save it to outputs/remote_dumps/html/.

    Parameters
    ----------
    url:  The full URL to fetch.
    name: Base filename (without .html extension).

    Returns the saved Path, or None if the fetch fails or returns non-200.
    """
    out_dir = _DUMPS_ROOT / "html"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers={"Accept": "text/html"})
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    path = out_dir / f"{name}.html"
    path.write_text(resp.text, encoding="utf-8")
    return path


def _ext_from_url(url: str) -> str:
    """Best-effort extension guess from URL path."""
    suffix = Path(url.split("?")[0]).suffix
    return suffix.lstrip(".") if suffix else ""
