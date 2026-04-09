"""
test_import_article.py — Playwright click-through tests for the Import Article screen.

Run:
    pytest tests/ui/screens/test_import_article.py -m browser --browser chromium -v
"""
import io
import pathlib
import struct
import tempfile
import zipfile
import zlib

import pytest
import requests as http

from tests.ui.conftest import BASE_URL

pytestmark = pytest.mark.browser

PLATFORM_URL = f"{BASE_URL}/screens/import-article/v1.html?mode=platform&returnTo=overview"
UPLOAD_URL = f"{BASE_URL}/screens/import-article/v1.html?mode=upload&returnTo=overview"
PLATFORM_CA_URL = f"{BASE_URL}/screens/import-article/v1.html?mode=platform&returnTo=create-article"

# ── Helpers ─────────────────────────────────────────────────────────────────


def goto_platform(page):
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)


def goto_upload(page):
    page.goto(UPLOAD_URL)
    page.wait_for_selector("#drop-zone", timeout=5000)


def advance(page):
    """Click the primary (Next / Import) button."""
    page.locator("#primary-btn").click()


# ── 1. Initial render — platform mode ────────────────────────────────────────


def test_platform_mode_shows_step_1_active(page):
    goto_platform(page)
    # Step bar: circle 1 is active, circles 2 and 3 are future
    circles = page.locator(".si-circle")
    assert "active" in circles.nth(0).get_attribute("class")
    assert "future" in circles.nth(1).get_attribute("class")
    assert "future" in circles.nth(2).get_attribute("class")


def test_platform_mode_renders_three_platform_cards(page):
    goto_platform(page)
    cards = page.locator(".platform-card")
    assert cards.count() == 3


def test_platform_mode_devto_is_disconnected(page):
    goto_platform(page)
    # Dev.to card has .disconnected class
    devto = page.locator(".platform-card").filter(has_text="Dev.to")
    assert "disconnected" in devto.get_attribute("class")


def test_platform_mode_next_disabled_before_selection(page):
    goto_platform(page)
    assert page.locator("#primary-btn").is_disabled()


def test_platform_mode_back_hidden_at_step_1(page):
    goto_platform(page)
    visibility = page.locator("#back-btn").evaluate("el => el.style.visibility")
    assert visibility == "hidden"


# ── 2. Platform selection ────────────────────────────────────────────────────


def test_selecting_medium_enables_next(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    assert not page.locator("#primary-btn").is_disabled()


def test_selecting_medium_shows_check(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    medium_card = page.locator(".platform-card").filter(has_text="Medium")
    assert "selected" in medium_card.get_attribute("class")


def test_cannot_select_disconnected_devto(page):
    goto_platform(page)
    devto = page.locator(".platform-card").filter(has_text="Dev.to")
    devto.click()
    # primary button should remain disabled
    assert page.locator("#primary-btn").is_disabled()


# ── 3. Step 1 → Step 2 (draft list) ─────────────────────────────────────────


def test_advancing_from_platform_shows_draft_list(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector("#draft-rows", timeout=3000)
    assert page.locator("#view-draft-list").is_visible()


def test_draft_list_shows_platform_name(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector("#platform-list-title", timeout=3000)
    assert "Medium" in page.locator("#platform-list-title").text_content()


def test_draft_list_shows_article_rows(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    assert page.locator(".draft-row").count() >= 1


def test_draft_list_shows_published_badge(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-badge", timeout=3000)
    badges = page.locator(".draft-badge")
    badge_texts = [badges.nth(i).text_content() for i in range(badges.count())]
    # Medium mock data has both draft and published articles
    assert any(t in ("draft", "published") for t in badge_texts)


def test_step_2_next_disabled_before_article_selection(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    assert page.locator("#primary-btn").is_disabled()


def test_step_2_back_visible(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector("#draft-rows", timeout=3000)
    visibility = page.locator("#back-btn").evaluate("el => el.style.visibility")
    assert visibility == "visible"


def test_step_2_circle_1_is_done(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".si-circle.done", timeout=3000)
    circles = page.locator(".si-circle")
    assert "done" in circles.nth(0).get_attribute("class")
    assert "active" in circles.nth(1).get_attribute("class")


# ── 4. Article selection ─────────────────────────────────────────────────────


def test_selecting_article_enables_next(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    assert not page.locator("#primary-btn").is_disabled()


def test_selecting_article_highlights_row(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    assert "selected" in page.locator(".draft-row").first.get_attribute("class")


# ── 5. Step 2 → Step 3 (review pane) ────────────────────────────────────────


def test_advancing_from_draft_list_shows_review(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#view-review", timeout=3000)
    assert page.locator("#view-review").is_visible()


def test_review_pane_shows_title_in_input(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#title-input", timeout=3000)
    title_value = page.locator("#title-input").input_value()
    assert len(title_value.strip()) > 0


def test_review_pane_shows_markdown_preview(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#markdown-preview", timeout=3000)
    assert len(page.locator("#markdown-preview").inner_html()) > 0


def test_review_primary_button_label_is_import(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#primary-btn", timeout=3000)
    assert "Import" in page.locator("#primary-btn").text_content()


def test_review_primary_enabled_with_title(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#title-input", timeout=3000)
    # Title is auto-filled from the selected article; button should be enabled
    assert not page.locator("#primary-btn").is_disabled()


def test_clearing_title_disables_import(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#title-input", timeout=3000)
    page.locator("#title-input").fill("")
    assert page.locator("#primary-btn").is_disabled()


def test_clicking_import_navigates_to_editor(page, requests_session):
    # Connect Medium so the import API accepts the platform source
    requests_session.put(f"{BASE_URL}/api/connections/medium", json={"token": "test-token"})
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#title-input", timeout=3000)
    with page.expect_navigation(timeout=8000):
        advance(page)
    assert "editor/" in page.url


# ── 6. Back navigation ───────────────────────────────────────────────────────


def test_back_from_draft_list_returns_to_platform_picker(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector("#draft-rows", timeout=3000)
    page.locator("#back-btn").click()
    assert page.locator("#view-platform-pick").is_visible()


def test_back_from_review_returns_to_draft_list(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#view-review", timeout=3000)
    page.locator("#back-btn").click()
    assert page.locator("#view-draft-list").is_visible()


def test_back_from_draft_list_step_bar_resets(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector("#draft-rows", timeout=3000)
    page.locator("#back-btn").click()
    circles = page.locator(".si-circle")
    assert "active" in circles.nth(0).get_attribute("class")
    assert "future" in circles.nth(1).get_attribute("class")


# ── 7. Cancel routing ────────────────────────────────────────────────────────


def test_cancel_with_return_to_overview_navigates_overview(page):
    goto_platform(page)
    with page.expect_navigation():
        page.locator("#cancel-link").click()
    assert "overview/v3.html" in page.url


def test_cancel_with_return_to_create_article_navigates_create_article(page):
    page.goto(PLATFORM_CA_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)
    with page.expect_navigation():
        page.locator("#cancel-link").click()
    assert "create-article/v1.html" in page.url


# ── 8. Hashnode platform ─────────────────────────────────────────────────────


def test_hashnode_shows_3_articles(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Hashnode").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    assert page.locator(".draft-row").count() == 3


# ── 9. Upload mode ───────────────────────────────────────────────────────────


def test_upload_mode_shows_drop_zone(page):
    goto_upload(page)
    assert page.locator("#drop-zone").is_visible()


def test_upload_mode_step_bar_has_2_steps(page):
    goto_upload(page)
    circles = page.locator(".si-circle")
    assert circles.count() == 2


def test_upload_mode_primary_disabled_before_file(page):
    goto_upload(page)
    assert page.locator("#primary-btn").is_disabled()


def test_upload_mode_back_hidden_at_step_1(page):
    goto_upload(page)
    visibility = page.locator("#back-btn").evaluate("el => el.style.visibility")
    assert visibility == "hidden"


def test_upload_mode_file_upload_advances_to_review(page):
    goto_upload(page)
    md_content = "# My Test Article\n\nThis is the article content.\n\nSome more words here."
    page.locator("#file-input").set_input_files({
        "name": "my-article.md",
        "mimeType": "text/markdown",
        "buffer": md_content.encode(),
    })
    page.wait_for_selector("#view-review", timeout=3000)
    assert page.locator("#view-review").is_visible()


def test_upload_mode_title_extracted_from_heading(page):
    goto_upload(page)
    md_content = "# My Test Article\n\nSome content here."
    page.locator("#file-input").set_input_files({
        "name": "my-article.md",
        "mimeType": "text/markdown",
        "buffer": md_content.encode(),
    })
    page.wait_for_selector("#title-input", timeout=3000)
    assert page.locator("#title-input").input_value() == "My Test Article"


def test_upload_mode_back_from_review_shows_drop_zone(page):
    goto_upload(page)
    md_content = "# Uploaded Article\n\nContent here."
    page.locator("#file-input").set_input_files({
        "name": "article.md",
        "mimeType": "text/markdown",
        "buffer": md_content.encode(),
    })
    page.wait_for_selector("#view-review", timeout=3000)
    page.locator("#back-btn").click()
    assert page.locator("#view-upload").is_visible()


def test_upload_mode_import_navigates_to_editor(page):
    goto_upload(page)
    md_content = "# Uploaded Article\n\nContent here with enough words."
    page.locator("#file-input").set_input_files({
        "name": "article.md",
        "mimeType": "text/markdown",
        "buffer": md_content.encode(),
    })
    page.wait_for_selector("#title-input", timeout=3000)
    with page.expect_navigation(timeout=8000):
        advance(page)
    assert "editor/" in page.url
    assert "id=art_" in page.url


# ── Helpers for multi-format tests ──────────────────────────────────────────


def _minimal_png() -> bytes:
    """1×1 white PNG."""

    def chunk(name, data):
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', crc)

    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b'\x00\xff\xff\xff')
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')


def _minimal_docx() -> bytes:
    """Minimal valid .docx with a Heading1 and a paragraph."""
    content_types = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        b'<Default Extension="xml" ContentType="application/xml"/>'
        b'<Override PartName="/word/document.xml"'
        b' ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        b'</Types>')
    rels = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rId1"'
        b' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
        b' Target="word/document.xml"/>'
        b'</Relationships>')
    doc_xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body>'
        b'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>DOCX Article</w:t></w:r></w:p>'
        b'<w:p><w:r><w:t>Paragraph content here.</w:t></w:r></w:p>'
        b'</w:body></w:document>')
    word_rels = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('word/document.xml', doc_xml)
        zf.writestr('word/_rels/document.xml.rels', word_rels)
    return buf.getvalue()


@pytest.fixture
def tmp_files(tmp_path):
    """Fixture files for all upload format tests."""
    png = _minimal_png()

    # plain .md, no image refs
    (tmp_path / "article.md").write_text("# Plain Article\n\nJust text, no images.\n",
                                         encoding="utf-8")
    # .md with relative image refs
    (tmp_path / "article_with_refs.md").write_text(
        "# Image Article\n\nSome text.\n\n![chart](chart.png)\n\n![logo](logo.png)\n",
        encoding="utf-8",
    )
    # companion images
    (tmp_path / "chart.png").write_bytes(png)
    (tmp_path / "logo.png").write_bytes(png)

    # unsupported file
    (tmp_path / "bad.txt").write_text("not a supported format", encoding="utf-8")

    # .html
    (tmp_path / "article.html").write_text(
        "<html><body><h1>HTML Article</h1><p>First paragraph.</p></body></html>",
        encoding="utf-8",
    )

    # .docx
    (tmp_path / "article.docx").write_bytes(_minimal_docx())

    # zip with md + image
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr("article.md", "# Zipped Article\n\nText.\n\n![chart](images/chart.png)\n")
        zf.writestr("images/chart.png", png)
    (tmp_path / "with_image.zip").write_bytes(buf.getvalue())

    # zip with md only
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, 'w') as zf:
        zf.writestr("article.md", "# Plain ZIP\n\nNo images here.\n")
    (tmp_path / "no_image.zip").write_bytes(buf2.getvalue())

    # zip with no md
    buf3 = io.BytesIO()
    with zipfile.ZipFile(buf3, 'w') as zf:
        zf.writestr("readme.txt", "not markdown")
    (tmp_path / "no_md.zip").write_bytes(buf3.getvalue())

    return tmp_path


# ── 9. Unsupported file type ─────────────────────────────────────────────────


def test_unsupported_file_shows_error(page, tmp_files):
    goto_upload(page)
    page.locator("#file-input").set_input_files(str(tmp_files / "bad.txt"))
    page.wait_for_selector("#drop-zone.error", timeout=3000)
    assert "error" in page.locator("#drop-zone").get_attribute("class")


# ── 10. ZIP upload ────────────────────────────────────────────────────────────


def test_zip_with_image_advances_to_review(page, tmp_files):
    goto_upload(page)
    page.locator("#file-input").set_input_files(str(tmp_files / "with_image.zip"))
    page.wait_for_selector("#view-review", timeout=8000)
    assert page.locator("#view-review").is_visible()


def test_zip_with_image_resolves_title(page, tmp_files):
    goto_upload(page)
    page.locator("#file-input").set_input_files(str(tmp_files / "with_image.zip"))
    page.wait_for_selector("#title-input", timeout=8000)
    assert page.locator("#title-input").input_value() == "Zipped Article"


def test_zip_no_image_advances_to_review(page, tmp_files):
    goto_upload(page)
    page.locator("#file-input").set_input_files(str(tmp_files / "no_image.zip"))
    page.wait_for_selector("#view-review", timeout=8000)
    assert page.locator("#view-review").is_visible()


def test_zip_no_md_shows_error(page, tmp_files):
    goto_upload(page)
    page.locator("#file-input").set_input_files(str(tmp_files / "no_md.zip"))
    page.wait_for_selector("#drop-zone.error", timeout=8000)
    assert "error" in page.locator("#drop-zone").get_attribute("class")


# ── 11. HTML upload ───────────────────────────────────────────────────────────


def test_html_advances_to_review(page, tmp_files):
    goto_upload(page)
    page.locator("#file-input").set_input_files(str(tmp_files / "article.html"))
    page.wait_for_selector("#view-review", timeout=8000)
    assert page.locator("#view-review").is_visible()


def test_html_extracts_title(page, tmp_files):
    goto_upload(page)
    page.locator("#file-input").set_input_files(str(tmp_files / "article.html"))
    page.wait_for_selector("#title-input", timeout=8000)
    assert page.locator("#title-input").input_value() == "HTML Article"


# ── 12. DOCX upload ───────────────────────────────────────────────────────────


def test_docx_advances_to_review(page, tmp_files):
    goto_upload(page)
    page.locator("#file-input").set_input_files(str(tmp_files / "article.docx"))
    page.wait_for_selector("#view-review", timeout=10000)
    assert page.locator("#view-review").is_visible()


# ── 13. .md + separate images multi-drop ─────────────────────────────────────


def test_md_with_companion_images_resolves_refs(page, tmp_files):
    goto_upload(page)
    page.locator("#file-input").set_input_files([
        str(tmp_files / "article_with_refs.md"),
        str(tmp_files / "chart.png"),
        str(tmp_files / "logo.png"),
    ])
    page.wait_for_selector("#view-review", timeout=8000)
    assert page.locator("#view-review").is_visible()
    # No warnings expected — all refs resolved
    warnings_el = page.locator("#review-warnings")
    if warnings_el.count() > 0:
        assert warnings_el.inner_text() == ""


def test_md_without_companion_images_advances(page, tmp_files):
    goto_upload(page)
    page.locator("#file-input").set_input_files(str(tmp_files / "article.md"))
    page.wait_for_selector("#view-review", timeout=5000)
    assert page.locator("#view-review").is_visible()


# ── 10. Cancel visibility ────────────────────────────────────────────────────


def test_cancel_visible_at_step_1(page):
    goto_platform(page)
    cancel = page.locator("#cancel-link")
    assert cancel.is_visible()


def test_cancel_hidden_at_step_2(page):
    """Cancel button is hidden after advancing to step 2 (draft list)."""
    goto_platform(page)
    # Hashnode is connected via env secret — card is clickable
    page.locator(".platform-card").filter(has_text="Hashnode").click()
    advance(page)
    # Even if drafts API returns 404 (no DB token), view-draft-list is shown
    page.wait_for_selector("#view-draft-list", timeout=5000)
    page.wait_for_function("document.getElementById('view-draft-list').style.display !== 'none'")
    display = page.locator("#cancel-link").evaluate("el => el.style.display")
    assert display == "none"


def test_cancel_hidden_at_step_3(page):
    """Cancel button is hidden on the review step — state injected via sessionStorage."""
    goto_platform(page)
    # Inject step-3 state with a pre-selected article so restore goes straight to review
    page.evaluate("""() => {
        sessionStorage.setItem('bh_import_v1', JSON.stringify({
            ts: Date.now(), mode: 'platform', step: 3,
            selectedPlatformId: 'hashnode',
            selectedArticle: {
                id: 'hn-draft-001', title: 'Test Article',
                snippet: 'Test snippet.', status: 'draft',
                wordCount: 500, age: 'today', coverImage: null,
                body: '# Test Article\\n\\nContent here.',
            },
            editedTitle: 'Test Article', draftSearch: '', draftFilter: 'all',
        }));
    }""")
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#view-review", timeout=8000)
    display = page.locator("#cancel-link").evaluate("el => el.style.display")
    assert display == "none"


def test_cancel_reappears_after_back_to_step_1(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Hashnode").click()
    advance(page)
    page.wait_for_selector("#view-draft-list", timeout=5000)
    page.locator("#back-btn").click()
    page.wait_for_selector("#platform-grid", timeout=3000)
    cancel = page.locator("#cancel-link")
    display = cancel.evaluate("el => el.style.display")
    assert display != "none"
    assert cancel.is_visible()


# ── 11. Start-over button ────────────────────────────────────────────────────


def test_startover_hidden_at_step_1(page):
    goto_platform(page)
    so = page.locator("#startover-btn")
    display = so.evaluate("el => el.style.display")
    assert display == "none"


def test_startover_visible_at_step_2(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Hashnode").click()
    advance(page)
    page.wait_for_selector("#view-draft-list", timeout=5000)
    so = page.locator("#startover-btn")
    assert so.is_visible()


def test_startover_appears_right_of_back_btn(page):
    """Start-over must follow back-btn in DOM order (rendered to its right)."""
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Hashnode").click()
    advance(page)
    page.wait_for_selector("#view-draft-list", timeout=5000)
    order = page.evaluate("""() => {
        const bar = document.getElementById('action-bar');
        const ids = [...bar.children].map(el => el.id);
        return { back: ids.indexOf('back-btn'), so: ids.indexOf('startover-btn') };
    }""")
    assert order["back"] < order["so"], (
        f"back-btn index {order['back']} should be before startover-btn index {order['so']}")


def test_startover_resets_to_step_1(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Hashnode").click()
    advance(page)
    page.wait_for_selector("#startover-btn", timeout=5000)
    page.locator("#startover-btn").click()
    page.wait_for_selector("#platform-grid", timeout=3000)
    circles = page.locator(".si-circle")
    assert "active" in circles.nth(0).get_attribute("class")


# ── 12. Session persistence (tab change simulation) ──────────────────────────


def _inject_import_state(page, *, step: int, platform_id: str = "hashnode") -> None:
    """Write sessionStorage directly to simulate a partially-completed wizard."""
    page.evaluate(f"""() => {{
        sessionStorage.setItem('bh_import_v1', JSON.stringify({{
            ts: Date.now(), mode: 'platform', step: {step},
            selectedPlatformId: '{platform_id}',
            selectedArticle: null,
            editedTitle: '', draftSearch: '', draftFilter: 'all',
        }}));
    }}""")


def test_session_persists_platform_selection_across_navigation(page):
    """Navigate away (to overview) then back — platform selection is restored."""
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Hashnode").click()
    # Navigate away and back (simulates switching tabs then returning)
    page.goto(f"{BASE_URL}/screens/overview/v3.html")
    page.wait_for_load_state("domcontentloaded")
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)
    selected = page.locator(".platform-card.selected")
    assert selected.count() == 1
    assert "Hashnode" in selected.text_content()


def test_session_persists_step_2_on_return(page):
    """After advancing to step 2 and navigating away, returning re-enters step 2."""
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Hashnode").click()
    advance(page)
    page.wait_for_selector("#view-draft-list", timeout=5000)
    # Navigate away and back
    page.goto(f"{BASE_URL}/screens/overview/v3.html")
    page.wait_for_load_state("domcontentloaded")
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#view-draft-list", timeout=5000)
    # Step 2 circle should be active
    circles = page.locator(".si-circle")
    assert "active" in circles.nth(1).get_attribute(
        "class"), "Step 2 should be active after restore"


def test_session_clears_on_startover(page):
    """Clicking Start over wipes sessionStorage — navigation returns to step 1 fresh."""
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Hashnode").click()
    advance(page)
    page.wait_for_selector("#startover-btn", timeout=5000)
    page.locator("#startover-btn").click()
    page.wait_for_selector("#platform-grid", timeout=3000)
    # Navigate away then back — should still be step 1 (no saved state)
    page.goto(f"{BASE_URL}/screens/overview/v3.html")
    page.wait_for_load_state("domcontentloaded")
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)
    circles = page.locator(".si-circle")
    assert "active" in circles.nth(0).get_attribute(
        "class"), "Should start at step 1 after start-over"
    assert "future" in circles.nth(1).get_attribute("class")


def test_session_mode_mismatch_ignored(page):
    """State saved with mode='upload' is ignored when loading platform mode URL."""
    # First load any page so sessionStorage is available in the same origin
    goto_platform(page)
    page.evaluate("""() => {
        sessionStorage.setItem('bh_import_v1', JSON.stringify({
            ts: Date.now(), mode: 'upload', step: 2,
            selectedPlatformId: 'hashnode',
            selectedArticle: null,
            editedTitle: '', draftSearch: '', draftFilter: 'all',
        }));
    }""")
    # Reload the platform URL — mode mismatch prevents restore
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)
    circles = page.locator(".si-circle")
    assert "active" in circles.nth(0).get_attribute("class")
