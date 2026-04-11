"""
test_visual_import_article.py — Screenshot every step of the Import Article screen.

Run:
    pytest tests/tests_ui/test_import_article/test_visual_import_article.py -m visual --browser chromium -v -s

Outputs → tests/tests_ui/outputs/screenshots/import_article/
"""
import io
import struct
import zlib

import pytest
import requests as http

from tests.tests_ui.conftest import BASE_URL
from tests.tests_ui.utils.screenshots import snap

pytestmark = pytest.mark.visual

PLATFORM_URL = f"{BASE_URL}/screens/import-article/v1.html?mode=platform&returnTo=overview"
UPLOAD_URL = f"{BASE_URL}/screens/import-article/v1.html?mode=upload&returnTo=overview"
SCREEN = "import_article"

# ── Helpers ───────────────────────────────────────────────────────────────────


def _minimal_png() -> bytes:
    """Return a minimal valid 1×1 white PNG."""

    def _chunk(name: bytes, data: bytes) -> bytes:
        c = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", c)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = _chunk(b"IDAT", zlib.compress(b"\x00\xFF\xFF\xFF"))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _connect_medium(base_url: str):
    http.put(f"{base_url}/api/connections/medium", json={"token": "test-token"}, timeout=5)


# ── Platform mode ─────────────────────────────────────────────────────────────


def test_visual_import_platform_step1(page):
    """Platform picker — step 1."""
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)
    snap(page, SCREEN, "platform_step1_default")


def test_visual_import_platform_step1_selected(page):
    """Platform picker — Medium card selected."""
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)
    page.locator(".platform-card").filter(has_text="Medium").click()
    snap(page, SCREEN, "platform_step1_medium_selected")


def test_visual_import_platform_step2_draft_list(page):
    """Draft list — step 2 after selecting Medium and advancing."""
    _connect_medium(BASE_URL)
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)
    page.locator(".platform-card").filter(has_text="Medium").click()
    page.locator("#primary-btn").click()
    page.wait_for_selector(".draft-row", timeout=15000)
    snap(page, SCREEN, "platform_step2_draft_list")


def test_visual_import_platform_step3_review(page):
    """Review pane — step 3 after selecting a draft."""
    _connect_medium(BASE_URL)
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)
    page.locator(".platform-card").filter(has_text="Medium").click()
    page.locator("#primary-btn").click()
    page.wait_for_selector(".draft-row", timeout=15000)
    page.locator(".draft-row").first.click()
    page.locator("#primary-btn").click()
    page.wait_for_selector("#view-review", timeout=10000)
    page.wait_for_function(
        "document.querySelector('#title-input').value.trim().length > 0",
        timeout=20000,
    )
    snap(page, SCREEN, "platform_step3_review")


# ── Upload mode ───────────────────────────────────────────────────────────────


def test_visual_import_upload_step1(page):
    """Upload drop zone — step 1."""
    page.goto(UPLOAD_URL)
    page.wait_for_selector("#drop-zone", timeout=5000)
    snap(page, SCREEN, "upload_step1_empty")


def test_visual_import_upload_step1_drag_active(page):
    """Upload drop zone — drag-hover active state (dragenter dispatched)."""
    page.goto(UPLOAD_URL)
    page.wait_for_selector("#drop-zone", timeout=5000)
    page.evaluate("""
        const dz = document.getElementById('drop-zone');
        dz.dispatchEvent(new DragEvent('dragenter', {bubbles: true}));
    """)
    page.wait_for_timeout(150)
    snap(page, SCREEN, "upload_step1_drag_active")


def test_visual_import_upload_step2_preview(page):
    """Upload preview — step 2 after dropping a PNG file."""
    page.goto(UPLOAD_URL)
    page.wait_for_selector("#drop-zone", timeout=5000)

    png_bytes = _minimal_png()
    page.evaluate(
        """([bytes, name]) => {
            const file = new File([new Uint8Array(bytes)], name, {type: 'image/png'});
            const dt = new DataTransfer();
            dt.items.add(file);
            const dz = document.getElementById('drop-zone');
            dz.dispatchEvent(new DragEvent('drop', {bubbles: true, dataTransfer: dt}));
        }""",
        [list(png_bytes), "cover.png"],
    )
    page.wait_for_timeout(500)
    snap(page, SCREEN, "upload_step2_png_preview")


def test_visual_import_upload_step2_md_preview(page):
    """Upload preview — step 2 after dropping a .md file."""
    page.goto(UPLOAD_URL)
    page.wait_for_selector("#drop-zone", timeout=5000)

    md = "# Hello\n\nThis is a test article body.\n"
    page.evaluate(
        """([content, name]) => {
            const file = new File([content], name, {type: 'text/markdown'});
            const dt = new DataTransfer();
            dt.items.add(file);
            const dz = document.getElementById('drop-zone');
            dz.dispatchEvent(new DragEvent('drop', {bubbles: true, dataTransfer: dt}));
        }""",
        [md, "article.md"],
    )
    page.wait_for_timeout(500)
    snap(page, SCREEN, "upload_step2_md_preview")
