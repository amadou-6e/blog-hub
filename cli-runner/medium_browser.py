"""Medium browser-profile checks for persistent Skyvern sessions."""
from __future__ import annotations

from html import unescape
import json
from pathlib import Path
import re
import sqlite3
import time

from markdown_it import MarkdownIt


_CHROMIUM_EPOCH_OFFSET_SECONDS = 11_644_473_600
_EDITOR_URL = "https://medium.com/new-story"
_DRAFTS_URL = "https://medium.com/me/stories/drafts"
_PUBLISHED_URL = "https://medium.com/me/stories/public"
_ARTICLE_ID_RE = re.compile(r"[A-Za-z0-9_-]{6,64}")


class MediumBrowserError(RuntimeError):
    pass


def _is_login_url(url: str) -> bool:
    lowered = url.lower()
    return any(part in lowered for part in ("/signin", "/m/signin", "/login"))


def _story_id(url: str) -> str | None:
    match = re.search(r"/p/([A-Za-z0-9_-]{6,64})/edit", url)
    return match.group(1) if match else None


def _article_html(article_md: str, title: str) -> str:
    body = article_md.lstrip()
    heading = re.match(r"^#\s+(.+?)(?:\n+|$)", body)
    if heading and heading.group(1).strip() == title.strip():
        body = body[heading.end():]
    return MarkdownIt("commonmark", {"html": False, "linkify": False}).enable(
        "table"
    ).render(body)


def _first_visible(page, selectors: tuple[str, ...]):
    for selector in selectors:
        candidate = page.locator(selector).first
        try:
            if candidate.is_visible(timeout=1_500):
                return candidate
        except Exception:
            continue
    return None


def _paste_html(page, article_html: str) -> None:
    staging = page.context.new_page()
    try:
        staging.set_content(f"<!doctype html><html><body>{article_html}</body></html>")
        staging.locator("body").click()
        staging.keyboard.press("Control+A")
        staging.keyboard.press("Control+C")
    finally:
        staging.close()
    page.bring_to_front()
    page.keyboard.press("Control+V")


def _replace_editor_content(page, *, title: str, article_html: str) -> None:
    page.wait_for_selector('[contenteditable="true"]', timeout=30_000)
    title_control = _first_visible(
        page,
        (
            'h1[data-testid="storyTitle"]',
            '[data-placeholder="Title"]',
            '[placeholder*="Title"]',
            'h1[contenteditable="true"]',
            '[contenteditable="true"]',
        ),
    )
    if title_control is None:
        raise MediumBrowserError("Medium title editor was not found")

    editables = page.locator('[contenteditable="true"]')
    title_control.click()
    page.keyboard.press("Control+A")
    page.keyboard.insert_text(title)
    if editables.count() > 1:
        editables.last.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
    else:
        page.keyboard.press("End")
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
    _paste_html(page, article_html)


def _text_tokens(value: str) -> list[str]:
    return re.findall(r"[\w']+", unescape(re.sub(r"<[^>]+>", " ", value)).lower())


def _verify_article(
    *, page, remote_id: str, title: str, article_html: str,
    expected_status: str,
) -> dict:
    page.wait_for_timeout(4_000)
    article = get_medium_article(page=page, article_id=remote_id)["article"]
    expected_tokens = _text_tokens(article_html)[:12]
    actual_tokens = set(_text_tokens(str(article.get("body") or "")))
    body_matches = not expected_tokens or all(
        token in actual_tokens for token in expected_tokens
    )
    if article.get("title") != title or not body_matches:
        raise MediumBrowserError("Medium article autosave could not be verified")
    if expected_status == "published" and article.get("status") != "published":
        raise MediumBrowserError("Medium public publish could not be verified")
    return article


def write_medium_article(
    *, page, title: str, article_md: str, remote_id: str | None = None,
    publish: bool = False,
) -> dict:
    """Create or update a Medium story and verify the resulting remote state."""
    if remote_id and not _ARTICLE_ID_RE.fullmatch(remote_id):
        raise ValueError("Invalid Medium article id")
    target_url = (
        f"https://medium.com/p/{remote_id}/edit" if remote_id else _EDITOR_URL
    )
    page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
    if _is_login_url(page.url):
        return {
            "success": False,
            "error": "Medium browser session is not authenticated",
            "manual_handoff": {
                "reason": "medium_login_required",
                "url": "https://medium.com/m/signin",
            },
        }

    html = _article_html(article_md, title)
    _replace_editor_content(page, title=title, article_html=html)
    deadline = time.monotonic() + 25
    while remote_id is None and time.monotonic() < deadline:
        remote_id = _story_id(page.url)
        if remote_id is None:
            page.wait_for_timeout(500)
    if remote_id is None:
        raise MediumBrowserError("Medium draft autosave did not return an article id")

    status = "draft"
    article = _verify_article(
        page=page, remote_id=remote_id, title=title,
        article_html=html, expected_status=status,
    )
    if publish:
        publish_button = page.get_by_role(
            "button", name=re.compile(r"^Publish$", re.I)
        ).first
        if not publish_button.is_visible(timeout=5_000):
            publish_button = page.locator('[data-action*="publish"]').first
        if not publish_button.is_visible(timeout=5_000):
            raise MediumBrowserError("Medium publish action was not found")
        publish_button.click()
        page.wait_for_timeout(1_000)
        confirmation = page.get_by_role(
            "button", name=re.compile(r"^Publish", re.I)
        ).last
        if not confirmation.is_visible(timeout=10_000):
            raise MediumBrowserError("Medium publish confirmation was not found")
        confirmation.click()
        article = _verify_article(
            page=page, remote_id=remote_id, title=title,
            article_html=html, expected_status="published",
        )
        status = "published"

    return {
        "success": True,
        "method": "deterministic",
        "status": status,
        "remote_id": remote_id,
        "draft_id": remote_id,
        "url": article.get("canonical_url")
        or f"https://medium.com/p/{remote_id}/edit",
        "article": article,
    }


def _list_source(page, *, status: str, url: str, limit: int) -> list[dict]:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    if _is_login_url(page.url):
        raise MediumBrowserError("Medium browser session is not authenticated")

    stable_rounds = 0
    previous_count = -1
    for _ in range(100):
        count = page.locator("h2").count()
        stable_rounds = stable_rounds + 1 if count == previous_count else 0
        if count >= limit or stable_rounds >= 2:
            break
        previous_count = count
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)

    return page.evaluate(
        r"""({status, limit}) => Array.from(document.querySelectorAll('h2')).map((heading) => {
          const container = heading.closest('article') || heading.parentElement?.parentElement?.parentElement;
          const root = container || heading.parentElement;
          const links = Array.from(root?.querySelectorAll('a[href]') || []);
          const edit = links.find((link) => /\/p\/[a-z0-9_-]+\/edit/i.test(link.href));
          const storyLink = heading.closest('a[href]') || links.find((link) => link.innerText.trim() === heading.innerText.trim());
          const publicLink = storyLink || links.find((link) => link.href.includes('medium.com/') && !link.href.includes('/me/stories'));
          const idMatch = edit?.href.match(/\/p\/([a-z0-9_-]+)\/edit/i);
          const publicId = publicLink?.href.match(/-([a-f0-9]{12})(?:[/?#]|$)/i)?.[1];
          const dataId = container?.getAttribute('data-post-id') || container?.querySelector('[data-post-id]')?.getAttribute('data-post-id');
          const remoteId = idMatch?.[1] || dataId || publicId || '';
          const href = ((status === 'draft' ? edit : publicLink) || edit || publicLink)?.href?.split('?')[0] || '';
          const text = (container?.innerText || '').replace(/\s+/g, ' ').trim();
          const words = text.match(/\((\d+)\s+words\)/i);
          const image = root?.querySelector('img[src]');
          const time = root?.querySelector('time');
          return {
            platform: 'medium',
            remote_id: remoteId,
            title: heading.innerText.trim(),
            body: '',
            status,
            subtitle: text.slice(0, 280),
            canonical_url: status === 'published' ? href || null : null,
            cover_url: image?.src || null,
            updated_at: time?.dateTime || time?.getAttribute('datetime') || null,
            metadata: {url: href || null, word_count: words ? Number(words[1]) : 0},
          };
        }).filter((item) => item.remote_id && item.title).slice(0, limit)""",
        {"status": status, "limit": limit},
    )


def list_medium_articles(*, page, limit: int = 100) -> dict:
    """List normalized Medium drafts and published stories without local writes."""
    articles: dict[str, dict] = {}
    errors: list[dict] = []
    for status, url in (("draft", _DRAFTS_URL), ("published", _PUBLISHED_URL)):
        try:
            rows = _list_source(page, status=status, url=url, limit=limit)
        except MediumBrowserError:
            errors.append({"source": status, "error": "medium_login_required"})
            continue
        except Exception:
            errors.append({"source": status, "error": "listing_retrieval_failed"})
            continue
        for row in rows:
            remote_id = str(row.get("remote_id") or "")
            if not remote_id:
                continue
            if remote_id not in articles or status == "published":
                articles[remote_id] = row
    failed = not articles and bool(errors)
    return {
        "success": not failed,
        "articles": list(articles.values()),
        "next_cursor": None,
        **({"error": errors[0]["error"]} if failed else {}),
        "diagnostics": {"errors": errors},
    }


def get_medium_article(*, page, article_id: str) -> dict:
    """Retrieve one Medium article as normalized Markdown and metadata."""
    if not _ARTICLE_ID_RE.fullmatch(article_id):
        raise ValueError("Invalid Medium article id")
    page.goto(
        f"https://medium.com/p/{article_id}/edit",
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    if _is_login_url(page.url):
        raise MediumBrowserError("Medium browser session is not authenticated")
    page.wait_for_timeout(1_000)
    article = page.evaluate(
        r"""(articleId) => {
          const root = document.querySelector('.postArticle-content, article, [data-testid="richTextEditor"], .pw-editor, main [contenteditable="true"]');
          if (!root) return null;
          const clone = root.cloneNode(true);
          const titleNode = clone.querySelector('h1, h2.graf--title, [data-testid="storyTitle"]');
          const title = (titleNode?.innerText || document.title.replace(/^Editing /, '').replace(/ [\u2013-] Medium$/, '')).trim();
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
          const stateText = Array.from(document.scripts).map((node) => node.textContent || '').find((text) => text.includes('canonicalUrl')) || '';
          const read = (name) => stateText.match(new RegExp(`"${name}":"([^"]*)"`))?.[1] || '';
          const number = (name) => Number(stateText.match(new RegExp(`"${name}":(\\d+)`))?.[1] || 0);
          const jsonLd = Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
            .map((node) => { try { return JSON.parse(node.textContent); } catch (_) { return null; } })
            .find((value) => value?.articleBody || value?.headline) || {};
          const canonicalUrl = read('canonicalUrl') || read('mediumUrl') || jsonLd.url || '';
          const jsonImage = typeof jsonLd.image === 'string' ? jsonLd.image : jsonLd.image?.url;
          const cover = jsonImage || clone.querySelector('img[src]')?.src || null;
          const domTags = Array.from(document.querySelectorAll('a[href*="/tag/"]')).map((node) => node.innerText.trim()).filter(Boolean);
          const jsonTags = Array.isArray(jsonLd.keywords) ? jsonLd.keywords : String(jsonLd.keywords || '').split(',');
          const tags = [...new Set([...domTags, ...jsonTags.map((tag) => tag.trim()).filter(Boolean)])];
          const subtitle = document.querySelector('h2[data-testid="storySubtitle"], h2.graf--subtitle')?.innerText?.trim() || jsonLd.description || null;
          const publishedMillis = number('latestPublishedAt');
          return {
            platform: 'medium',
            remote_id: articleId,
            title,
            body: render(clone).replace(/\n{3,}/g, '\n\n').trim(),
            status: number('latestPublishedAt') > 0 ? 'published' : 'draft',
            subtitle,
            canonical_url: canonicalUrl || null,
            cover_url: cover,
            tags,
            updated_at: jsonLd.dateModified || read('updatedAt') || null,
            published_at: jsonLd.datePublished || (publishedMillis ? new Date(publishedMillis).toISOString() : null),
            metadata: {url: canonicalUrl || null},
          };
        }""",
        article_id,
    )
    if not article or not article.get("title"):
        raise MediumBrowserError("Medium article content was not found")
    return {"success": True, "article": article}


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
