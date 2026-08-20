from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3


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
