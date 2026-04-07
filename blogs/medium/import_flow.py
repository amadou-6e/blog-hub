from __future__ import annotations

import re
from pathlib import Path


_IMPORT_TEXTBOX_SELECTOR = (
    'div.textInput.textInput--large.js-importUrl.editable[role="textbox"]'
)


def import_url_via_medium(page, source_url: str, *, dump_dir: str | Path | None = None) -> str:
    """
    Import a public URL into Medium using the same interaction that previously
    worked in ``article_publishing``.

    This intentionally uses the stricter hydrated textbox selector plus
    keyboard-based entry instead of Playwright ``fill()``, because that older
    interaction has proven more reliable with Medium's import page.
    """
    page.goto("https://medium.com/p/import", wait_until="networkidle")
    page.wait_for_timeout(3_000)

    if dump_dir is not None:
        dump_path = Path(dump_dir)
        dump_path.mkdir(parents=True, exist_ok=True)
        Path(dump_path, "import_page.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(Path(dump_path, "import_page.png")), full_page=True)

    textbox = None
    for selector in (
        _IMPORT_TEXTBOX_SELECTOR,
        'div.js-importUrl[contenteditable="true"]',
        'div.textInput.textInput--large.js-importUrl',
        'div.js-importUrl',
        'div[role="textbox"]',
    ):
        candidate = page.locator(selector).first
        try:
            candidate.wait_for(state="visible", timeout=10_000)
            textbox = candidate
            break
        except Exception:
            continue
    if textbox is None:
        raise RuntimeError("Could not locate Medium import textbox.")
    textbox.click()
    page.keyboard.press("Meta+A" if page.evaluate("() => navigator.platform") == "MacIntel" else "Control+A")
    page.keyboard.type(source_url)
    page.wait_for_timeout(1_000)

    import_button = page.get_by_role("button", name="Import")
    import_button.click()

    page.wait_for_timeout(3_000)
    if dump_dir is not None:
        page.screenshot(path=str(Path(dump_dir, "post_click.png")), full_page=True)

    page.wait_for_url(
        lambda url: re.search(r"medium\.com/p/.+/edit", str(url)) is not None,
        timeout=180_000,
    )
    return page.url
