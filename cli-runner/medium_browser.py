"""Deterministic Medium operations using a persisted Skyvern browser profile."""
from __future__ import annotations

import json
from html import unescape
from pathlib import Path
import sqlite3
import time
import re


_CHROMIUM_EPOCH_OFFSET_SECONDS = 11_644_473_600


_EDITOR_URL = "https://medium.com/new-story"
_DRAFTS_URL = "https://medium.com/me/stories/drafts"
_PUBLISHED_URL = "https://medium.com/me/stories/public"


class MediumBrowserError(RuntimeError):
    pass


def _launch_context(playwright, profile_dir: str):
    return playwright.chromium.launch_persistent_context(
        profile_dir,
        headless=True,
        viewport={"width": 1440, "height": 1000},
        permissions=["clipboard-read", "clipboard-write"],
    )


def _is_login_url(url: str) -> bool:
    lowered = url.lower()
    return any(part in lowered for part in ("/signin", "/m/signin", "/login"))


def _story_id(url: str) -> str | None:
    match = re.search(r"/p/([a-f0-9]+)/edit", url)
    return match.group(1) if match else None


def upload_medium_draft(
    *, profile_dir: str, title: str, article_html: str, publish: bool = False,
) -> dict:
    """Create a Medium draft by pasting rendered HTML into the rich editor."""
    from patchright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(_EDITOR_URL, wait_until="domcontentloaded", timeout=60_000)
            if _is_login_url(page.url):
                return {"success": False, "error": "Medium browser session is not authenticated"}
            page.wait_for_selector('[contenteditable="true"]', timeout=30_000)

            title_control = None
            for selector in (
                'h1[data-testid="storyTitle"]', '[data-placeholder="Title"]',
                '[placeholder*="Title"]', 'h1[contenteditable="true"]',
                '[contenteditable="true"]',
            ):
                candidate = page.locator(selector).first
                try:
                    if candidate.is_visible(timeout=1500):
                        title_control = candidate
                        break
                except Exception:
                    continue
            if title_control is None:
                raise MediumBrowserError("Medium title editor was not found")

            title_control.click()
            page.keyboard.press("Control+A")
            page.keyboard.insert_text(title)
            page.keyboard.press("End")
            page.keyboard.press("Enter")
            page.keyboard.press("Enter")

            staging = context.new_page()
            staging.set_content(f"<!doctype html><html><body>{article_html}</body></html>")
            staging.locator("body").click()
            staging.keyboard.press("Control+A")
            staging.keyboard.press("Control+C")
            staging.close()
            page.bring_to_front()
            page.keyboard.press("Control+V")

            deadline = time.monotonic() + 25
            while _story_id(page.url) is None and time.monotonic() < deadline:
                page.wait_for_timeout(500)
            draft_url = page.url
            draft_id = _story_id(draft_url)
            if draft_id is None:
                return {"success": False, "error": "Medium draft autosave did not return an article id"}

            page.wait_for_timeout(4_000)
            page.reload(wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_selector('[contenteditable="true"]', timeout=30_000)
            visible_text = " ".join(page.locator("body").inner_text().split())
            expected_body = " ".join(
                unescape(re.sub(r"<[^>]+>", " ", article_html)).split()
            )
            body_probe = expected_body[:120].strip()
            if title not in visible_text or (body_probe and body_probe not in visible_text):
                return {
                    "success": False,
                    "error": "Medium draft autosave could not be verified",
                    "url": draft_url,
                    "draft_id": draft_id,
                }

            result_url = draft_url
            status = "draft"
            if publish:
                publish_button = page.get_by_role("button", name=re.compile("^Publish$", re.I)).first
                if not publish_button.is_visible(timeout=5_000):
                    publish_button = page.locator('[data-action*="publish"]').first
                publish_button.click()
                page.wait_for_timeout(1_000)
                confirm = page.get_by_role("button", name=re.compile("^Publish", re.I)).last
                if not confirm.is_visible(timeout=10_000):
                    raise MediumBrowserError("Medium publish confirmation was not found")
                confirm.click()
                deadline = time.monotonic() + 45
                while "/edit" in page.url and time.monotonic() < deadline:
                    page.wait_for_timeout(500)
                result_url = page.url
                status = "published"
                if "/edit" in result_url:
                    return {
                        "success": False,
                        "error": "Medium public publish could not be verified",
                        "url": draft_url,
                        "draft_id": draft_id,
                    }

            return {
                "success": True,
                "method": "deterministic",
                "status": status,
                "url": result_url,
                "draft_id": draft_id,
            }
        finally:
            context.close()


def list_medium_articles(*, profile_dir: str) -> dict:
    """List the signed-in user's Medium drafts and published stories."""
    from patchright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            articles: list[dict] = []
            for status, url in (("draft", _DRAFTS_URL), ("published", _PUBLISHED_URL)):
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                if _is_login_url(page.url):
                    raise MediumBrowserError("Medium browser session is not authenticated")
                page.wait_for_timeout(2_000)
                for _ in range(8):
                    previous = page.locator("h2").count()
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(700)
                    if page.locator("h2").count() == previous:
                        break
                rows = page.evaluate(
                    r"""(status) => Array.from(document.querySelectorAll('h2')).map((heading) => {
                      const container = heading.closest('article') || heading.parentElement?.parentElement?.parentElement;
                      const links = Array.from((container || heading.parentElement).querySelectorAll('a[href]'));
                      const edit = links.find((link) => /\/p\/[a-f0-9]+\/edit/.test(link.href));
                      const storyLink = heading.closest('a[href]') || links.find((link) => link.innerText.trim() === heading.innerText.trim());
                      const publicLink = storyLink || links.find((link) => link.href.includes('medium.com/') && !link.href.includes('/me/stories'));
                      const href = (status === 'draft' ? edit : publicLink) || edit || publicLink;
                      const text = (container?.innerText || '').replace(/\s+/g, ' ').trim();
                      const words = text.match(/\((\d+)\s+words\)/i);
                      const idMatch = edit?.href.match(/\/p\/([a-f0-9]+)\/edit/);
                      const publicId = publicLink?.href.match(/-([a-f0-9]{12})(?:[/?#]|$)/)?.[1];
                      const dataId = container?.getAttribute('data-post-id') || container?.querySelector('[data-post-id]')?.getAttribute('data-post-id');
                      return {
                        id: idMatch?.[1] || dataId || publicId || '', title: heading.innerText.trim(),
                        url: href?.href?.split('?')[0] || '', status,
                        word_count: words ? Number(words[1]) : 0,
                        updated_at: '', snippet: text.slice(0, 280),
                      };
                    }).filter((item) => item.id && item.title)""",
                    status,
                )
                articles.extend(rows)
            deduped = {f"{item['status']}:{item['id']}": item for item in articles}
            return {"articles": list(deduped.values())}
        finally:
            context.close()


def get_medium_article(*, profile_dir: str, article_id: str) -> dict:
    """Retrieve Medium article metadata and a Markdown representation of its body."""
    from patchright.sync_api import sync_playwright

    if not re.fullmatch(r"[A-Za-z0-9_-]+", article_id):
        raise ValueError("Invalid Medium article id")
    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(
                f"https://medium.com/p/{article_id}/edit",
                wait_until="domcontentloaded", timeout=60_000,
            )
            if _is_login_url(page.url):
                raise MediumBrowserError("Medium browser session is not authenticated")
            page.wait_for_timeout(2_000)
            article = page.evaluate(
                r"""(articleId) => {
                  const root = document.querySelector('.postArticle-content, article, [data-testid="richTextEditor"], .pw-editor');
                  if (!root) return null;
                  const clone = root.cloneNode(true);
                  const titleNode = clone.querySelector('h1, h2.graf--title, [data-testid="storyTitle"]');
                  const title = (titleNode?.innerText || document.title.replace(/^Editing /, '').replace(/ – Medium$/, '')).trim();
                  if (titleNode) titleNode.remove();
                  const render = (node) => {
                    if (node.nodeType === Node.TEXT_NODE) return node.textContent;
                    if (node.nodeType !== Node.ELEMENT_NODE) return '';
                    const tag = node.tagName.toLowerCase();
                    const inside = Array.from(node.childNodes).map(render).join('');
                    if (tag === 'img') return `![${node.alt || ''}](${node.src || ''})`;
                    if (tag === 'a') return `[${inside}](${node.href})`;
                    if (tag === 'strong' || tag === 'b') return `**${inside}**`;
                    if (tag === 'em' || tag === 'i') return `*${inside}*`;
                    if (tag === 'code' && node.parentElement?.tagName.toLowerCase() !== 'pre') return `\`${inside}\``;
                    if (tag === 'pre') return `\n\n\`\`\`\n${node.innerText}\n\`\`\`\n\n`;
                    if (tag === 'h2') return `\n\n## ${inside.trim()}\n\n`;
                    if (tag === 'h3') return `\n\n### ${inside.trim()}\n\n`;
                    if (tag === 'blockquote') return `\n\n> ${node.innerText.replace(/\n/g, '\n> ')}\n\n`;
                    if (tag === 'li') return `\n- ${inside.trim()}`;
                    if (tag === 'p' || tag === 'figure') return `\n\n${inside.trim()}\n\n`;
                    if (tag === 'br') return '\n';
                    return inside;
                  };
                  const jsonLd = Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                    .map((node) => { try { return JSON.parse(node.textContent); } catch (_) { return null; } })
                    .find((value) => value?.articleId === articleId) || {};
                  const stateText = Array.from(document.scripts).map((node) => node.textContent || '').find((text) => text.includes('canonicalUrl')) || '';
                  const canonicalMatch = stateText.match(/"canonicalUrl":"([^"]*)"/);
                  const mediumUrlMatch = stateText.match(/"mediumUrl":"([^"]*)"/);
                  const publishedMatch = stateText.match(/"latestPublishedAt":(\d+)/);
                  const canonicalUrl = canonicalMatch?.[1] || mediumUrlMatch?.[1] || '';
                  return {
                    id: articleId, title, body: render(clone).replace(/\n{3,}/g, '\n\n').trim(),
                    word_count: Number(jsonLd.wordCount || 0),
                    updated_at: jsonLd.dateModified || '',
                    status: Number(publishedMatch?.[1] || 0) > 0 ? 'published' : 'draft',
                    canonical_url: canonicalUrl || (jsonLd.url && !jsonLd.url.endsWith('/edit') ? jsonLd.url : null),
                    cover_image: typeof jsonLd.image === 'string' ? jsonLd.image : jsonLd.image?.url || null,
                  };
                }""",
                article_id,
            )
            if not article:
                raise MediumBrowserError("Medium article content was not found")
            if not article["word_count"]:
                article["word_count"] = len(article["body"].split())
            return article
        finally:
            context.close()

def check_medium_profile(*, profile_dir: str) -> dict:
    profile = Path(profile_dir)
    authenticated = _chromium_cookie_db_has_medium_session(profile)
    if not authenticated:
        authenticated = _cookie_snapshot_has_medium_session(profile)
    return {
        "authenticated": authenticated,
        "status": "connected" if authenticated else "login_required",
    }


def _is_medium_session_cookie(domain: object, name: object) -> bool:
    normalized_domain = str(domain or "").lstrip(".")
    return (
        normalized_domain == "medium.com"
        and str(name or "") in {"sid", "uid", "lightstep_guid"}
    )


def _cookie_is_not_expired(expires: object) -> bool:
    try:
        value = float(expires)
    except (TypeError, ValueError):
        return True
    return value < 0 or value > time.time()


def _chromium_cookie_is_not_expired(expires_utc: object) -> bool:
    try:
        value = int(expires_utc)
    except (TypeError, ValueError):
        return False
    if value == 0:
        return True
    expires_unix = value / 1_000_000 - _CHROMIUM_EPOCH_OFFSET_SECONDS
    return expires_unix > time.time()


def _chromium_cookie_db_has_medium_session(profile: Path) -> bool:
    candidates = [
        profile / "Default" / "Cookies",
        profile / "Cookies",
    ]
    for db_path in candidates:
        if not db_path.exists():
            continue
        try:
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            rows = connection.execute(
                "SELECT host_key, name, expires_utc, value, encrypted_value FROM cookies"
            ).fetchall()
        except sqlite3.Error:
            continue
        finally:
            try:
                connection.close()
            except Exception:
                pass
        has_uid = False
        has_sid = False
        for domain, name, expires_utc, value, encrypted_value in rows:
            if not _is_medium_session_cookie(domain, name):
                continue
            if not _chromium_cookie_is_not_expired(expires_utc):
                continue
            if not (value or encrypted_value):
                continue
            has_uid = has_uid or name == "uid"
            has_sid = has_sid or name == "sid"
        if has_uid and has_sid:
            return True
    return False


def _cookie_snapshot_has_medium_session(profile: Path) -> bool:
    snapshot = profile / ".skyvern_session_cookies.json"
    try:
        cookies = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(cookies, list):
        return False
    names = {
        str(cookie.get("name") or "")
        for cookie in cookies
        if isinstance(cookie, dict)
        and _is_medium_session_cookie(cookie.get("domain"), cookie.get("name"))
        and _cookie_is_not_expired(cookie.get("expires"))
        and cookie.get("value")
    }
    return {"sid", "uid"}.issubset(names)
