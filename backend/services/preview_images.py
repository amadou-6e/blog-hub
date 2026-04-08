"""Preview image resolution for overview cards."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


_PREVIEW_DIR = Path(Path(__file__).resolve().parents[2], "generated_previews")
_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
_SCRIPT_PATH = Path(Path(__file__).resolve().parents[2], "scripts", "capture_preview.mjs")


def resolve_preview_image_url(*, article_id: str, title_image_url: str | None, page_url: str | None) -> str | None:
    """Prefer the title image; otherwise create and cache a page screenshot."""
    if title_image_url:
        return title_image_url
    if not page_url:
        return None

    output_name = _preview_filename(article_id, page_url)
    output_path = Path(_PREVIEW_DIR, output_name)
    if not output_path.exists():
        _capture_preview_screenshot(page_url, output_path)
    if output_path.exists():
        return f"/generated-previews/{output_name}"
    return None


def _preview_filename(article_id: str, page_url: str) -> str:
    digest = hashlib.sha1(page_url.encode("utf-8")).hexdigest()[:12]
    return f"{article_id}-{digest}.png"


def _capture_preview_screenshot(page_url: str, output_path: Path) -> None:
    command = [
        "node",
        str(_SCRIPT_PATH),
        page_url,
        str(output_path),
    ]
    try:
        subprocess.run(command, check=True, timeout=45, capture_output=True, text=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return
