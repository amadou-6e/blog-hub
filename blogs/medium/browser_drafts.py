"""
Browser-backed Medium draft listing and deletion utilities.

These helpers are intentionally self-contained inside blog-hub and do not rely
on the external medium-mcp-server runtime code. They mirror the previously
working browser flow from article_publishing, but remove the single-batch
assumption by collecting drafts across repeated scroll passes.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import time
from pathlib import Path


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_BROWSER_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=VizDisplayCompositor,TranslateUI",
    "--disable-ipc-flooding-protection",
]


@dataclass(frozen=True)
class MediumDraft:
    title: str
    url: str
    updated_text: str
    read_time_text: str
    word_count: int | None


@dataclass(frozen=True)
class MediumDraftInventory:
    drafts: tuple[MediumDraft, ...]
    visible_urls: tuple[str, ...]
    first_title: str | None

    @property
    def count(self) -> int:
        return len(self.drafts)


@dataclass(frozen=True)
class DeleteDraftsResult:
    deleted: tuple[MediumDraft, ...]
    kept: tuple[MediumDraft, ...]
    rounds: tuple[dict, ...]


class MediumBrowserDraftError(RuntimeError):
    """Raised when browser-based Medium draft management fails."""


class MediumBrowserDraftClient:
    """List and delete Medium drafts using an authenticated browser session."""

    def __init__(self, session_file: str | None = None) -> None:
        self._session_file = session_file or find_medium_session_file()
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None

    def __enter__(self) -> "MediumBrowserDraftClient":
        self.initialize()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def initialize(self) -> None:
        if self.page is not None:
            return
        if self._session_file is None:
            raise MediumBrowserDraftError("No Medium session file found.")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise MediumBrowserDraftError(
                "Playwright is not installed in the current Python environment."
            ) from exc

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=False,
            args=_BROWSER_ARGS,
        )
        self._context = self._browser.new_context(
            storage_state=self._session_file,
            user_agent=_USER_AGENT,
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        self.page = self._context.new_page()
        self.page.set_default_timeout(120_000)
        self.page.set_default_navigation_timeout(120_000)

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None

    def ensure_logged_in(self) -> None:
        self.initialize()
        assert self.page is not None
        self.page.goto("https://medium.com/new-story", wait_until="load")
        self.page.wait_for_timeout(3_000)
        logged_in = self.page.evaluate(
            """() => {
                const selectors = [
                  'button[aria-label*="user"]',
                  'a[href*="/me/lists"]',
                  '[data-testid="headerUserButton"]',
                  '[contenteditable="true"]',
                ];
                return selectors.some((selector) => document.querySelector(selector));
            }"""
        )
        if not logged_in:
            raise MediumBrowserDraftError(
                f"Medium session appears expired. Current URL: {self.page.url}"
            )

    def list_drafts(self, title_filter: str = "") -> list[MediumDraft]:
        return list(self.inspect_drafts(title_filter).drafts)

    def inspect_drafts(self, title_filter: str = "") -> MediumDraftInventory:
        self.ensure_logged_in()
        assert self.page is not None
        self.page.goto("https://medium.com/me/stories/drafts", wait_until="networkidle")
        self.page.wait_for_timeout(2_000)
        self._scroll_drafts_page_until_stable()
        raw_items = self.page.evaluate(
            """(filterTitle) => {
                const normalizedFilter = (filterTitle || '').trim().toLowerCase();
                const anchors = Array.from(document.querySelectorAll('a[href*="/edit"]'));
                const seen = new Set();
                const rows = [];
                for (const anchor of anchors) {
                    const href = (anchor.href || '').split('?')[0];
                    if (!href || seen.has(href)) {
                        continue;
                    }
                    let current = anchor;
                    let row = null;
                    while (current) {
                        const buttons = Array.from(current.querySelectorAll('button'));
                        const hasActionButton = buttons.some((button) =>
                            (button.textContent || '').includes('Toggle actions menu')
                        );
                        if (hasActionButton) {
                            row = current;
                            break;
                        }
                        current = current.parentElement;
                    }
                    if (!row) {
                        continue;
                    }
                    const titleElement = row.querySelector('h2');
                    const title = (titleElement?.textContent || '').trim();
                    if (!title) {
                        continue;
                    }
                    if (normalizedFilter && !title.toLowerCase().includes(normalizedFilter)) {
                        continue;
                    }
                    const metaText = (row.textContent || '').replace(/\\s+/g, ' ').trim();
                    const wordCountMatch = metaText.match(/\\((\\d+)\\s+words\\)/i);
                    const updatedMatch = metaText.match(/Updated\\s+(.+?)Toggle actions menu/i);
                    const readTimeMatch = metaText.match(/(\\d+\\s+min read)/i);
                    seen.add(href);
                    rows.push({
                        title,
                        url: href,
                        updated_text: updatedMatch?.[1]?.trim() || '',
                        read_time_text: readTimeMatch?.[1] || '',
                        word_count: wordCountMatch ? Number(wordCountMatch[1]) : null,
                    });
                }
                return rows;
            }""",
            title_filter,
        )
        drafts = tuple(
            MediumDraft(
                title=item["title"],
                url=item["url"],
                updated_text=item.get("updated_text") or "",
                read_time_text=item.get("read_time_text") or "",
                word_count=item.get("word_count"),
            )
            for item in raw_items
        )
        return MediumDraftInventory(
            drafts=drafts,
            visible_urls=tuple(draft.url for draft in drafts),
            first_title=drafts[0].title if drafts else None,
        )

    def count_drafts(self, title_filter: str = "") -> int:
        return self.inspect_drafts(title_filter).count

    def delete_drafts(self, title_filter: str = "", keep_newest: int = 0) -> DeleteDraftsResult:
        deleted: list[MediumDraft] = []
        kept: tuple[MediumDraft, ...] = ()
        rounds: list[dict] = []

        previous_urls: tuple[str, ...] | None = None
        for round_index in range(1, 11):
            inventory = self.inspect_drafts(title_filter)
            drafts = inventory.drafts
            current_urls = inventory.visible_urls
            if not drafts:
                rounds.append({"round": round_index, "visible_count": 0, "done": True})
                return DeleteDraftsResult(tuple(deleted), kept, tuple(rounds))
            if previous_urls == current_urls:
                rounds.append(
                    {
                        "round": round_index,
                        "visible_count": len(drafts),
                        "first_title": inventory.first_title,
                        "visible_urls": current_urls,
                        "stalled": True,
                    }
                )
                return DeleteDraftsResult(tuple(deleted), kept, tuple(rounds))

            previous_urls = current_urls
            kept = tuple(drafts[:keep_newest])
            to_delete = drafts[keep_newest:]
            if not to_delete:
                rounds.append(
                    {
                        "round": round_index,
                        "visible_count": len(drafts),
                        "first_title": inventory.first_title,
                        "done": True,
                        "kept_count": len(kept),
                    }
                )
                return DeleteDraftsResult(tuple(deleted), kept, tuple(rounds))

            deleted_this_round = 0
            for draft in to_delete:
                if self._delete_one_draft(draft.url):
                    deleted.append(draft)
                    deleted_this_round += 1
            rounds.append(
                {
                    "round": round_index,
                    "visible_count": len(drafts),
                    "first_title_before": inventory.first_title,
                    "visible_urls_before": current_urls,
                    "deleted_this_round": deleted_this_round,
                    "kept_count": len(kept),
                }
            )
            if deleted_this_round == 0:
                return DeleteDraftsResult(tuple(deleted), kept, tuple(rounds))

        return DeleteDraftsResult(tuple(deleted), kept, tuple(rounds))

    def _scroll_drafts_page_until_stable(self) -> None:
        assert self.page is not None
        previous_count = -1
        stable_rounds = 0
        for _ in range(12):
            visible_count = self.page.evaluate(
                "() => new Set(Array.from(document.querySelectorAll('a[href*=\"/edit\"]')).map((a) => (a.href || '').split('?')[0]).filter(Boolean)).size"
            )
            if visible_count == previous_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                previous_count = visible_count
            if stable_rounds >= 2:
                break
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self.page.wait_for_timeout(1_200)
        self.page.evaluate("window.scrollTo(0, 0)")
        self.page.wait_for_timeout(600)

    def _delete_one_draft(self, draft_url: str) -> bool:
        assert self.page is not None
        self.page.goto("https://medium.com/me/stories/drafts", wait_until="networkidle")
        self.page.wait_for_timeout(1_500)
        self._scroll_drafts_page_until_stable()

        opened_menu = self.page.evaluate(
            """(targetUrl) => {
                const normalizedTargetUrl = targetUrl.split('?')[0];
                const links = Array.from(document.querySelectorAll('a[href*="/edit"]'));
                const link = links.find((candidate) => (candidate.href || '').split('?')[0] === normalizedTargetUrl);
                if (!link) {
                    return false;
                }
                let current = link;
                while (current) {
                    const button = Array.from(current.querySelectorAll('button')).find((candidate) =>
                        (candidate.textContent || '').includes('Toggle actions menu')
                    );
                    if (button) {
                        button.click();
                        return true;
                    }
                    current = current.parentElement;
                }
                return false;
            }""",
            draft_url,
        )
        if not opened_menu:
            return False

        self.page.wait_for_timeout(1_000)
        clicked_delete = self.page.evaluate(
            """() => {
                const labels = ['Delete story', 'Delete draft', 'Delete'];
                const candidates = Array.from(document.querySelectorAll('button'));
                const button = candidates.find((candidate) => labels.includes((candidate.textContent || '').trim()));
                if (!button) {
                    return false;
                }
                button.click();
                return true;
            }"""
        )
        if not clicked_delete:
            return False

        self.page.wait_for_timeout(1_000)
        confirmed_delete = self.page.evaluate(
            """() => {
                const candidates = Array.from(document.querySelectorAll('button'));
                const button = candidates.find((candidate) => {
                    const text = (candidate.textContent || '').trim();
                    return text === 'Delete' || text === 'Confirm delete';
                });
                if (!button) {
                    return false;
                }
                button.click();
                return true;
            }"""
        )
        if not confirmed_delete:
            return False

        self.page.wait_for_timeout(1_500)
        return True


def find_medium_session_file() -> str | None:
    candidates = [
        os.environ.get("MEDIUM_SESSION_FILE", "").strip(),
        r"C:\Users\acisse\Documents\CodeWorkspace\medium-mcp-server\medium-session.json",
        str(
            Path(
                Path(__file__).resolve().parents[3],
                "article_publishing",
                "config",
                "medium-session.json",
            )
        ),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None
