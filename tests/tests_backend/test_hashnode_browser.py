from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import sys


RUNNER = Path(__file__).resolve().parents[2] / "cli-runner"
sys.path.insert(0, str(RUNNER))
spec = importlib.util.spec_from_file_location("hashnode_browser_under_test", RUNNER / "hashnode_browser.py")
hashnode_browser = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(hashnode_browser)


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
