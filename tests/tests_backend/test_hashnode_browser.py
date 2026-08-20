from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace


RUNNER = Path(__file__).resolve().parents[2] / "cli-runner"
sys.path.insert(0, str(RUNNER))
spec = importlib.util.spec_from_file_location("hashnode_browser_under_test", RUNNER / "hashnode_browser.py")
hashnode_browser = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(hashnode_browser)


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def is_visible(self, timeout=None):
        return self.selector in self.page.visible

    def fill(self, value):
        self.page.filled[self.selector] = value

    def click(self):
        self.page.clicked.append(self.selector)
        if self.selector == "button:has-text('Write')":
            self.page.url = "https://hashnode.com/draft/current"
            self.page.visible.update({
                "button:has-text('New')",
                "button:has-text('Publish')",
                "textarea[placeholder*='title' i]",
                "button:has-text('Markdown')",
            })
        elif self.selector == "button:has-text('New')":
            self.page.url = "https://hashnode.com/draft/draft_test"
            self.page.filled.clear()
        elif self.selector == "button:has-text('Markdown')":
            self.page.visible.add("textarea[placeholder*='writing markdown' i]")
        elif self.selector == "button:has-text('Publish')":
            self.page.visible.add("[role='dialog'] button:has-text('Publish')")
        elif self.selector == "[role='dialog'] button:has-text('Publish')":
            self.page.url = "https://hashnode.com/edit/post_test"

    def input_value(self):
        return self.page.filled.get(self.selector, "")

    def evaluate_all(self, _script):
        return [{"tag": "textarea", "placeholder": "Article title"}]


class FakePage:
    def __init__(self):
        self.url = "https://hashnode.com"
        self.visible = {"button:has-text('Write')"}
        self.filled = {}
        self.clicked = []
        self.cookies = []
        self.request = FakeRequest(self)

    def goto(self, *_args, **_kwargs):
        return None

    def locator(self, selector):
        return FakeLocator(self, selector)

    def wait_for_timeout(self, _timeout):
        return None

    def wait_for_url(self, _url, timeout=None):
        return None

    def reload(self, **_kwargs):
        return None


class FakeResponse:
    ok = True

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeRequest:
    def __init__(self, page):
        self.page = page

    def get(self, _url):
        return FakeResponse({
            "success": True,
            "post": {
                "isActive": True,
                "title": self.page.filled[
                    "textarea[placeholder*='title' i]"
                ],
                "contentMarkdown": self.page.filled[
                    "textarea[placeholder*='writing markdown' i]"
                ],
                "slug": "test-article",
                "publication": {"username": "tensorworks"},
            },
        })


class FakeContext:
    def __init__(self, page):
        self.pages = [page]

    def close(self):
        return None

    def cookies(self, _urls=None):
        return self.pages[0].cookies


class FakePlaywright:
    def __init__(self, page):
        self.chromium = SimpleNamespace(
            launch_persistent_context=lambda *_args, **_kwargs: FakeContext(page)
        )


class PlaywrightManager:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        return FakePlaywright(self.page)

    def __exit__(self, *_args):
        return None


def test_deterministic_selectors_fill_and_verify_autosaved_draft(monkeypatch):
    page = FakePage()
    sync_api = SimpleNamespace(sync_playwright=lambda: PlaywrightManager(page))
    monkeypatch.setitem(sys.modules, "patchright.sync_api", sync_api)
    result = hashnode_browser.upload_hashnode_draft(
        profile_dir="/tmp/profile", title="A title", article_md="# A title",
    )

    assert result["success"] is True
    assert result["method"] == "deterministic"
    assert result["draft_id"] == "draft_test"
    assert page.filled["textarea[placeholder*='title' i]"] == "A title"
    assert page.filled["textarea[placeholder*='writing markdown' i]"] == "# A title"


def test_extension_page_entrypoint_uses_core_owned_page():
    page = FakePage()

    result = hashnode_browser.upload_hashnode_page(
        page, title="Extension title", article_md="# Extension title"
    )

    assert result["success"] is True
    assert result["draft_id"] == "draft_test"
    assert page.filled["textarea[placeholder*='title' i]"] == "Extension title"


def test_missing_deterministic_selector_fails(monkeypatch):
    page = FakePage()
    page.visible.clear()
    sync_api = SimpleNamespace(sync_playwright=lambda: PlaywrightManager(page))
    monkeypatch.setitem(sys.modules, "patchright.sync_api", sync_api)
    try:
        hashnode_browser.upload_hashnode_draft(
            profile_dir="/tmp/profile", title="A title", article_md="# A title",
        )
    except hashnode_browser.SelectorFailure as exc:
        assert exc.action == "editor_entry"
    else:
        raise AssertionError("missing selector was accepted")


def test_hashnode_markdown_normalization_accepts_editor_formatting():
    original = "![Diagram](https://example.com/a.png)\n\n- first\n- second"
    persisted = (
        '![Diagram](https://example.com/a.png align="center")\n\n'
        "*   first\n    \n*   second"
    )

    assert (
        hashnode_browser._normalized_markdown(persisted)
        == hashnode_browser._normalized_markdown(original)
    )


def test_public_publish_requires_final_confirmation(monkeypatch):
    page = FakePage()
    sync_api = SimpleNamespace(sync_playwright=lambda: PlaywrightManager(page))
    monkeypatch.setitem(sys.modules, "patchright.sync_api", sync_api)

    result = hashnode_browser.upload_hashnode_draft(
        profile_dir="/tmp/profile",
        title="A title",
        article_md="# A title",
        publish=True,
    )

    assert result["success"] is True
    assert result["status"] == "published"
    assert result["url"] == "https://tensorworks.hashnode.dev/test-article"
    assert result["post_id"] == "post_test"
    assert "[role='dialog'] button:has-text('Publish')" in page.clicked


def _write_cookie_snapshot(profile_dir, cookies):
    (profile_dir / ".skyvern_session_cookies.json").write_text(
        __import__("json").dumps(cookies), encoding="utf-8"
    )


def test_profile_check_rejects_a_profile_without_session_cookie(tmp_path):
    _write_cookie_snapshot(tmp_path, [
        {"domain": "hashnode.com", "name": "__Host-authjs.csrf-token", "value": "opaque"},
    ])
    result = hashnode_browser.check_hashnode_profile(profile_dir=str(tmp_path))
    assert result == {"authenticated": False, "status": "login_required"}


def test_profile_check_accepts_hashnode_session_snapshot(tmp_path):
    _write_cookie_snapshot(tmp_path, [
        {"domain": "hashnode.com", "name": "hashnode-session", "value": "opaque", "expires": -1},
    ])

    result = hashnode_browser.check_hashnode_profile(profile_dir=str(tmp_path))

    assert result == {"authenticated": True, "status": "connected"}


def test_profile_check_accepts_chunked_authjs_session_snapshot(tmp_path):
    _write_cookie_snapshot(tmp_path, [
        {"domain": ".hashnode.com", "name": "__Secure-authjs.session-token.0", "value": "opaque"},
    ])

    result = hashnode_browser.check_hashnode_profile(profile_dir=str(tmp_path))

    assert result == {"authenticated": True, "status": "connected"}


def test_profile_check_rejects_expired_session_cookie(tmp_path):
    _write_cookie_snapshot(tmp_path, [
        {"domain": "hashnode.com", "name": "hashnode-session", "value": "expired", "expires": 1},
    ])

    result = hashnode_browser.check_hashnode_profile(profile_dir=str(tmp_path))

    assert result == {"authenticated": False, "status": "login_required"}


def test_profile_check_accepts_encrypted_chromium_hashnode_session(tmp_path):
    cookie_db = tmp_path / "Default" / "Cookies"
    cookie_db.parent.mkdir()
    connection = sqlite3.connect(cookie_db)
    connection.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, expires_utc INTEGER, "
        "value TEXT, encrypted_value BLOB)"
    )
    connection.execute(
        "INSERT INTO cookies VALUES (?, ?, ?, ?, ?)",
        ("hashnode.com", "hashnode-session", 99_999_999_999_999_999, "", b"encrypted"),
    )
    connection.commit()
    connection.close()

    result = hashnode_browser.check_hashnode_profile(profile_dir=str(tmp_path))

    assert result == {"authenticated": True, "status": "connected"}
