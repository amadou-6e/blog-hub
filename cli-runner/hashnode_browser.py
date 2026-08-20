"""Deterministic Hashnode draft upload through a persisted browser profile."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import time

SELECTORS_PATH = Path(__file__).with_name("browser_selectors.json")


class SelectorFailure(RuntimeError):
    def __init__(self, action: str):
        super().__init__(f"Hashnode control not found: {action}")
        self.action = action


def _first_visible(page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=1200):
                return locator, selector
        except Exception:
            continue
    return None, None


def _wait_first_visible(page, selectors: list[str], *, timeout_ms: int = 20_000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        locator, selector = _first_visible(page, selectors)
        if locator is not None:
            return locator, selector
        page.wait_for_timeout(250)
    return None, None


def _draft_id(url: str) -> str | None:
    marker = "/draft/"
    return url.rstrip("/").split(marker, 1)[1] if marker in url else None


def _edit_id(url: str) -> str | None:
    marker = "/edit/"
    return url.rstrip("/").split(marker, 1)[1] if marker in url else None


def _normalized_markdown(markdown: str) -> str:
    normalized = re.sub(
        r'(!\[[^\]]*\]\([^\s)]+)\s+align="center"(\))',
        r"\1\2",
        markdown,
    )
    normalized = re.sub(r"^\*\s{3}", "- ", normalized, flags=re.MULTILINE)
    normalized = re.sub(r"^\s+$", "", normalized, flags=re.MULTILINE)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"(^- .+)\n\n(?=- )", r"\1\n", normalized, flags=re.MULTILINE)
    return normalized.strip()


def _remote_timestamp(value: object) -> str | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _image_url(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        candidate = value.get("url")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _browser_article(payload: dict, *, remote_id: str, published: bool) -> dict:
    publication = payload.get("publication") or {}
    publication_name = publication.get("username") if isinstance(publication, dict) else None
    slug = payload.get("slug")
    public_url = (
        f"https://{publication_name}.hashnode.dev/{slug}"
        if published and publication_name and slug else None
    )
    title = str(payload.get("title") or "").strip()
    if not title and not published:
        title = f"Untitled Hashnode draft ({remote_id[:8]})"
    return {
        "remote_id": str(payload.get("cuid") or payload.get("_id") or remote_id),
        "title": title,
        "body": str(payload.get("contentMarkdown") or ""),
        "status": "published" if published else "draft",
        "subtitle": str(payload.get("subtitle") or "").strip() or None,
        "canonical_url": str(payload.get("originalArticleURL") or "").strip() or None,
        "updated_at": _remote_timestamp(payload.get("dateUpdated")),
        "created_at": _remote_timestamp(payload.get("dateAdded")),
        "cover_url": _image_url(payload.get("coverImage") or payload.get("ogImage")),
        "metadata": {"url": public_url},
    }


def _listing_ids(page, *, published: bool) -> list[str]:
    marker = "/edit/" if published else "/draft/"
    selector = f'a[href*="{marker}"]'
    hrefs = page.locator(selector).evaluate_all("els => els.map(e => e.href)")
    result: list[str] = []
    for href in hrefs:
        remote_id = str(href).rstrip("/").rsplit(marker, 1)[-1].split("?", 1)[0]
        if remote_id and remote_id not in result:
            result.append(remote_id)
    return result


def _wait_for_listing(page, *, published: bool, timeout_ms: int = 25_000) -> bool:
    selector = 'a[href*="/edit/"]' if published else 'a[href*="/draft/"]'
    label = "Published" if published else "Drafts"
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if page.locator(selector).count():
            return True
        try:
            body = page.locator("body").inner_text()
            match = re.search(rf"(?:^|\n){label}\s*\n(\d+)(?:\n|$)", body)
            if match and int(match.group(1)) == 0:
                return True
        except Exception:
            pass
        page.wait_for_timeout(250)
    return False


def _exhaust_listing(page, selectors: dict, *, max_clicks: int = 100) -> bool:
    """Click every Hashnode load-more batch. Returns False on a stalled control."""
    article_links = 'a[href*="/draft/"], a[href*="/edit/"]'
    for _ in range(max_clicks):
        load_more, _ = _first_visible(page, selectors["load_more"])
        if load_more is None:
            return True
        before = len(page.locator(article_links).all())
        load_more.click()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            page.wait_for_timeout(250)
            if len(page.locator(article_links).all()) > before:
                break
        else:
            return False
    return False


def retrieve_hashnode_articles(*, page) -> dict:
    """Retrieve all Hashnode drafts and posts through the extension runtime page."""
    selectors = json.loads(SELECTORS_PATH.read_text(encoding="utf-8"))
    articles: list[dict] = []
    errors: list[dict] = []
    for source, published, tab_selector in (
        ("drafts", False, "drafts_tab"),
        ("published", True, "published_tab"),
    ):
        try:
            page.goto(
                "https://hashnode.com/drafts",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            if any(part in page.url.lower() for part in ("signin", "login", "onboard")):
                errors.append({"source": source, "error": "hashnode_login_required"})
                continue
            tab, _ = _wait_first_visible(
                page, selectors[tab_selector], timeout_ms=25_000,
            )
            if tab is None:
                errors.append({"source": source, "error": "listing_tab_unavailable"})
                continue
            tab.click()
            if not _wait_for_listing(page, published=published):
                errors.append({"source": source, "error": "listing_retrieval_failed"})
                continue
            if not _exhaust_listing(page, selectors):
                errors.append({"source": source, "error": "listing_pagination_stalled"})
            remote_ids = _listing_ids(page, published=published)
        except Exception:
            errors.append({"source": source, "error": "listing_retrieval_failed"})
            continue

        endpoint = "posts" if published else "drafts"
        payload_key = "post" if published else "draft"
        for remote_id in remote_ids:
            try:
                response = page.request.get(
                    f"https://hashnode.com/api/{endpoint}/{remote_id}"
                )
                payload = response.json() if response.ok else {}
                record = payload.get(payload_key) if payload.get("success") else None
                if not isinstance(record, dict):
                    raise ValueError("article payload unavailable")
                article = _browser_article(
                    record, remote_id=remote_id, published=published,
                )
                if not article["title"]:
                    raise ValueError("article title unavailable")
                articles.append(article)
            except Exception:
                errors.append({
                    "source": source,
                    "remote_id": remote_id,
                    "error": "article_retrieval_failed",
                })

    return {
        "success": True,
        "articles": articles,
        "diagnostics": {"errors": errors},
    }


def upload_hashnode_draft(
    *, profile_dir: str, title: str, article_md: str, publish: bool = False,
) -> dict:
    """Compatibility wrapper; new extensions receive a core-owned page."""
    from patchright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile_dir, headless=True, viewport={"width": 1440, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            return upload_hashnode_page(
                page, title=title, article_md=article_md, publish=publish
            )
        finally:
            context.close()


def upload_hashnode_page(
    page, *, title: str, article_md: str, publish: bool = False,
) -> dict:
    """Run Hashnode automation on a page owned by the extension runtime."""
    selectors = json.loads(SELECTORS_PATH.read_text(encoding="utf-8"))
    page.goto(selectors["editor_url"], wait_until="domcontentloaded", timeout=45000)
    if any(part in page.url.lower() for part in ("signin", "login", "onboard")):
        return {
            "success": False,
            "error": "Hashnode browser session is not authenticated",
            "manual_handoff": {
                "reason": "hashnode_login_required",
                "url": "https://hashnode.com/login",
            },
        }

    editor_entry, _ = _wait_first_visible(page, selectors["editor_entry"])
    if editor_entry is None:
        raise SelectorFailure("editor_entry")
    editor_entry.click()
    page.wait_for_url("**/draft/**", timeout=30_000)
    previous_draft_url = page.url
    new_draft, _ = _wait_first_visible(
        page, selectors["new_draft"], timeout_ms=60_000
    )
    if new_draft is None:
        raise SelectorFailure("new_draft")
    new_draft.click()
    deadline = time.monotonic() + 30
    while page.url == previous_draft_url and time.monotonic() < deadline:
        page.wait_for_timeout(250)
    if page.url == previous_draft_url:
        raise SelectorFailure("new_draft")

    title_control, _ = _wait_first_visible(page, selectors["title"])
    markdown_mode, _ = _wait_first_visible(page, selectors["markdown_mode"])
    if title_control is None:
        raise SelectorFailure("title")
    if markdown_mode is None:
        raise SelectorFailure("markdown_mode")
    markdown_mode.click()
    content_control, _ = _wait_first_visible(page, selectors["content"])
    if content_control is None:
        raise SelectorFailure("content")

    title_control.fill(title)
    content_control.fill(article_md)
    draft_url = page.url
    draft_id = _draft_id(draft_url)

    # Hashnode autosaves drafts. A reload is the strongest deterministic
    # confirmation available without clicking the public Publish action.
    page.wait_for_timeout(6_000)
    page.reload(wait_until="domcontentloaded", timeout=45_000)
    title_control, _ = _wait_first_visible(page, selectors["title"])
    content_control, _ = _wait_first_visible(
        page, selectors["content"], timeout_ms=2_000
    )
    if content_control is None:
        markdown_mode, _ = _wait_first_visible(page, selectors["markdown_mode"])
        if markdown_mode is not None:
            markdown_mode.click()
            content_control, _ = _wait_first_visible(page, selectors["content"])
    if (
        title_control is None
        or content_control is None
        or title_control.input_value() != title
        or _normalized_markdown(content_control.input_value())
        != _normalized_markdown(article_md)
    ):
        return {
            "success": False,
            "error": "Hashnode draft autosave could not be verified",
            "url": draft_url,
            "draft_id": draft_id,
        }
    if publish:
        publish_open, _ = _wait_first_visible(page, selectors["publish_open"])
        if publish_open is None:
            raise SelectorFailure("publish_open")
        publish_open.click()
        publish_confirm, _ = _wait_first_visible(page, selectors["publish_confirm"])
        if publish_confirm is None:
            raise SelectorFailure("publish_confirm")
        publish_confirm.click()
        deadline = time.monotonic() + 45
        while "/draft/" in page.url and time.monotonic() < deadline:
            page.wait_for_timeout(250)
        if "/draft/" in page.url:
            return {
                "success": False,
                "error": "Hashnode public publish could not be verified",
                "url": draft_url,
                "draft_id": draft_id,
            }
        post_id = _edit_id(page.url)
        if post_id is None:
            return {
                "success": False,
                "error": "Hashnode published post identifier was not returned",
                "url": page.url,
                "draft_id": draft_id,
            }
        response = page.request.get(f"https://hashnode.com/api/posts/{post_id}")
        metadata = response.json() if response.ok else {}
        post = metadata.get("post") if metadata.get("success") else None
        if (
            not post
            or not post.get("isActive")
            or post.get("title") != title
            or _normalized_markdown(post.get("contentMarkdown") or "")
            != _normalized_markdown(article_md)
        ):
            return {
                "success": False,
                "error": "Hashnode published post could not be verified",
                "url": page.url,
                "draft_id": draft_id,
            }
        publication = post.get("publication") or {}
        publication_name = publication.get("username")
        slug = post.get("slug")
        if not publication_name or not slug:
            return {
                "success": False,
                "error": "Hashnode public article URL was not returned",
                "url": page.url,
                "draft_id": draft_id,
            }
        public_url = f"https://{publication_name}.hashnode.dev/{slug}"

    result = {
        "success": True,
        "method": "deterministic",
        "status": "published" if publish else "draft",
        "url": public_url if publish else draft_url,
        "draft_id": draft_id,
    }
    if publish:
        result["post_id"] = post_id
    return result


def check_hashnode_profile(*, profile_dir: str) -> dict:
    """Verify a closed Chromium profile without launching another browser."""
    profile = Path(profile_dir)
    authenticated = _chromium_cookie_db_has_hashnode_session(profile)
    if not authenticated:
        authenticated = _cookie_snapshot_has_hashnode_session(profile)
    return {
        "authenticated": authenticated,
        "status": "connected" if authenticated else "login_required",
    }


def _is_hashnode_session_cookie(domain: object, name: object) -> bool:
    return (
        str(domain or "").lstrip(".") == "hashnode.com"
        and (
            name in {"authjs.session-token", "hashnode-session"}
            or str(name or "").startswith("__Secure-authjs.session-token")
        )
    )


def _chromium_cookie_db_has_hashnode_session(profile: Path) -> bool:
    # Chromium stores expiry as microseconds since 1601-01-01 UTC.
    chrome_now = int((time.time() + 11_644_473_600) * 1_000_000)
    for cookie_db in (profile / "Default" / "Cookies", profile / "Cookies"):
        if not cookie_db.is_file():
            continue
        try:
            connection = sqlite3.connect(f"file:{cookie_db}?mode=ro", uri=True)
            try:
                rows = connection.execute(
                    "SELECT host_key, name, expires_utc, length(value), "
                    "length(encrypted_value) FROM cookies"
                )
                if any(
                    _is_hashnode_session_cookie(domain, name)
                    and (int(value_length or 0) + int(encrypted_length or 0) > 0)
                    and (not expires or int(expires) > chrome_now)
                    for domain, name, expires, value_length, encrypted_length in rows
                ):
                    return True
            finally:
                connection.close()
        except (OSError, sqlite3.Error, TypeError, ValueError):
            continue
    return False


def _cookie_snapshot_has_hashnode_session(profile: Path) -> bool:
    snapshot = profile / ".skyvern_session_cookies.json"
    try:
        cookies = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        cookies = []
    if not isinstance(cookies, list):
        cookies = []
    now = time.time()
    return any(
        isinstance(cookie, dict)
        and _is_hashnode_session_cookie(cookie.get("domain"), cookie.get("name"))
        and bool(cookie.get("value"))
        and (
            not isinstance(cookie.get("expires"), (int, float))
            or cookie["expires"] <= 0
            or cookie["expires"] > now
        )
        for cookie in cookies
    )
