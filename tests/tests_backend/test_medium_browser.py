from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import time

import pytest


RUNNER = Path(__file__).resolve().parents[2] / "cli-runner"
spec = importlib.util.spec_from_file_location(
    "medium_browser_under_test", RUNNER / "medium_browser.py"
)
medium_browser = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(medium_browser)


def _write_cookie_snapshot(profile_dir, cookies):
    (profile_dir / ".skyvern_session_cookies.json").write_text(
        __import__("json").dumps(cookies), encoding="utf-8"
    )


def test_profile_check_rejects_profile_without_medium_session(tmp_path):
    _write_cookie_snapshot(tmp_path, [
        {"domain": ".medium.com", "name": "xsrf", "value": "opaque"},
    ])

    result = medium_browser.check_medium_profile(profile_dir=str(tmp_path))

    assert result == {"authenticated": False, "status": "login_required"}


def test_profile_check_accepts_medium_session_snapshot(tmp_path):
    _write_cookie_snapshot(tmp_path, [
        {"domain": ".medium.com", "name": "uid", "value": "user"},
        {"domain": ".medium.com", "name": "sid", "value": "session"},
    ])

    result = medium_browser.check_medium_profile(profile_dir=str(tmp_path))

    assert result == {"authenticated": True, "status": "connected"}


def test_profile_check_accepts_encrypted_chromium_medium_session(tmp_path):
    cookie_db = tmp_path / "Default" / "Cookies"
    cookie_db.parent.mkdir()
    connection = sqlite3.connect(cookie_db)
    connection.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, expires_utc INTEGER, "
        "value TEXT, encrypted_value BLOB)"
    )
    connection.executemany(
        "INSERT INTO cookies VALUES (?, ?, ?, ?, ?)",
        [
            (".medium.com", "uid", 99_999_999_999_999_999, "", b"encrypted"),
            (".medium.com", "sid", 99_999_999_999_999_999, "", b"encrypted"),
        ],
    )
    connection.commit()
    connection.close()

    result = medium_browser.check_medium_profile(profile_dir=str(tmp_path))

    assert result == {"authenticated": True, "status": "connected"}


def test_profile_check_rejects_expired_chromium_medium_session(tmp_path):
    cookie_db = tmp_path / "Default" / "Cookies"
    cookie_db.parent.mkdir()
    connection = sqlite3.connect(cookie_db)
    connection.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, expires_utc INTEGER, "
        "value TEXT, encrypted_value BLOB)"
    )
    expired_utc = int((time.time() + 11_644_473_600 - 60) * 1_000_000)
    connection.executemany(
        "INSERT INTO cookies VALUES (?, ?, ?, ?, ?)",
        [
            (".medium.com", "uid", expired_utc, "", b"encrypted"),
            (".medium.com", "sid", expired_utc, "", b"encrypted"),
        ],
    )
    connection.commit()
    connection.close()

    result = medium_browser.check_medium_profile(profile_dir=str(tmp_path))

    assert result == {"authenticated": False, "status": "login_required"}


class _HeadingLocator:
    def __init__(self, page):
        self.page = page

    def count(self):
        return len(self.page.rows.get(self.page.status, []))


class _MediumPage:
    def __init__(self, *, rows=None, article=None, fail_status=None, login=False):
        self.url = "about:blank"
        self.status = "draft"
        self.rows = rows or {"draft": [], "published": []}
        self.article = article
        self.fail_status = fail_status
        self.login = login

    def goto(self, url, **_kwargs):
        self.status = "published" if url.endswith("/public") else "draft"
        if self.status == self.fail_status:
            raise RuntimeError("fixture listing failed")
        self.url = "https://medium.com/m/signin" if self.login else url

    def locator(self, _selector):
        return _HeadingLocator(self)

    def evaluate(self, script, argument=None):
        if "window.scrollTo" in script:
            return None
        if isinstance(argument, dict):
            return self.rows[argument["status"]][:argument["limit"]]
        return self.article

    def wait_for_timeout(self, _timeout):
        return None


def _summary(remote_id, status, title):
    return {
        "platform": "medium",
        "remote_id": remote_id,
        "title": title,
        "body": "",
        "status": status,
        "subtitle": f"{title} summary",
        "canonical_url": f"https://medium.com/@author/{remote_id}" if status == "published" else None,
        "cover_url": None,
        "updated_at": "2026-08-20T10:00:00Z",
        "metadata": {"url": f"https://medium.com/p/{remote_id}/edit", "word_count": 12},
    }


def test_listing_normalizes_drafts_and_published_stories():
    page = _MediumPage(rows={
        "draft": [_summary("draft123abc", "draft", "Draft story")],
        "published": [_summary("public123abc", "published", "Public story")],
    })

    result = medium_browser.list_medium_articles(page=page, limit=50)

    assert result["success"] is True
    assert result["next_cursor"] is None
    assert result["diagnostics"] == {"errors": []}
    assert [(item["remote_id"], item["status"]) for item in result["articles"]] == [
        ("draft123abc", "draft"),
        ("public123abc", "published"),
    ]


def test_listing_returns_partial_results_with_structured_source_error():
    page = _MediumPage(
        rows={
            "draft": [_summary("draft123abc", "draft", "Draft story")],
            "published": [],
        },
        fail_status="published",
    )

    result = medium_browser.list_medium_articles(page=page)

    assert len(result["articles"]) == 1
    assert result["diagnostics"]["errors"] == [{
        "source": "published", "error": "listing_retrieval_failed",
    }]


def test_listing_reports_stale_browser_profile_as_failed_operation():
    result = medium_browser.list_medium_articles(page=_MediumPage(login=True))

    assert result["success"] is False
    assert result["error"] == "medium_login_required"
    assert result["articles"] == []
    assert len(result["diagnostics"]["errors"]) == 2


def test_detail_returns_normalized_article():
    normalized = {
        "platform": "medium",
        "remote_id": "abc123def456",
        "title": "A Medium story",
        "body": "## Section\n\nBody with ![image](https://cdn.example/image.png)",
        "status": "published",
        "subtitle": "A subtitle",
        "canonical_url": "https://example.com/canonical",
        "cover_url": "https://cdn.example/cover.png",
        "tags": ["Python"],
        "updated_at": "2026-08-20T10:00:00Z",
        "published_at": "2026-08-19T10:00:00Z",
        "metadata": {"url": "https://example.com/canonical"},
    }
    page = _MediumPage(article=normalized)

    result = medium_browser.get_medium_article(
        page=page, article_id="abc123def456",
    )

    assert result == {"success": True, "article": normalized}
    assert result["article"]["platform"] == "medium"
    assert page.url == "https://medium.com/p/abc123def456/edit"


def test_detail_rejects_invalid_remote_id_before_navigation():
    page = _MediumPage()

    with pytest.raises(ValueError, match="Invalid Medium article id"):
        medium_browser.get_medium_article(page=page, article_id="../cookie")

    assert page.url == "about:blank"
