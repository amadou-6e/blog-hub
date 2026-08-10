from __future__ import annotations

import logging
import os
import stat

import pytest
from cryptography.fernet import Fernet

from backend.security import SecretRedactionFilter, redact_secrets
from backend.store.backends.sqlite import SQLiteStore
from backend.store.crypto import (
    CredentialConfigurationError,
    CredentialDecryptionError,
    configure_key_provider,
    decrypt_token,
    encrypt_token,
    get_key_provider,
    rotate_file_key,
)


@pytest.fixture
def credential_environment(tmp_path, monkeypatch):
    key_file = tmp_path / "keys" / "credential-keys.json"
    monkeypatch.delenv("BLOGHUB_SECRET_KEY", raising=False)
    monkeypatch.delenv("BLOGHUB_SECRET_KEY_ID", raising=False)
    monkeypatch.delenv("BLOGHUB_PREVIOUS_SECRET_KEYS", raising=False)
    monkeypatch.setenv("BLOGHUB_CREDENTIAL_KEY_FILE", str(key_file))
    configure_key_provider(None)
    yield tmp_path, key_file
    configure_key_provider(None)


def _store(tmp_path) -> SQLiteStore:
    return SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))


def test_default_key_file_encrypts_without_plaintext(credential_environment):
    tmp_path, key_file = credential_environment
    store = _store(tmp_path)
    result = store.save_connection(store.SEED_USER_ID, "anthropic", "sk-ant-secret")
    raw = store._con.execute(
        "SELECT token FROM connections WHERE platform='anthropic'"
    ).fetchone()[0]

    assert result.get("token") is None
    assert raw.startswith("enc:v1:")
    assert "sk-ant-secret" not in raw
    assert store.get_connection_token(store.SEED_USER_ID, "anthropic") == "sk-ant-secret"
    if os.name == "posix":
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_startup_migrates_plaintext_and_disconnect_erases_it(credential_environment):
    tmp_path, _ = credential_environment
    store = _store(tmp_path)
    store.save_connection(store.SEED_USER_ID, "devto", "initial")
    store._con.execute(
        "UPDATE connections SET token='legacy-secret' WHERE platform='devto'"
    )
    store._con.commit()
    store._con.close()

    reopened = _store(tmp_path)
    raw = reopened._con.execute(
        "SELECT token FROM connections WHERE platform='devto'"
    ).fetchone()[0]
    assert raw.startswith("enc:v1:")
    assert "legacy-secret" not in raw
    assert reopened.get_connection_token(reopened.SEED_USER_ID, "devto") == "legacy-secret"

    reopened.delete_connection(reopened.SEED_USER_ID, "devto")
    row = reopened._con.execute(
        "SELECT token, status FROM connections WHERE platform='devto'"
    ).fetchone()
    assert tuple(row) == ("", "disconnected")


def test_startup_migrates_legacy_fernet_ciphertext(credential_environment):
    tmp_path, _ = credential_environment
    store = _store(tmp_path)
    _, key = get_key_provider().active_key()
    legacy = "fernet:" + Fernet(key).encrypt(b"legacy-encrypted-secret").decode()
    store.save_connection(store.SEED_USER_ID, "devto", "initial")
    store._con.execute(
        "UPDATE connections SET token=? WHERE platform='devto'", (legacy,)
    )
    store._con.commit()
    store._con.close()

    reopened = _store(tmp_path)
    raw = reopened._con.execute(
        "SELECT token FROM connections WHERE platform='devto'"
    ).fetchone()[0]
    assert raw.startswith("enc:v1:")
    assert reopened.get_connection_token(reopened.SEED_USER_ID, "devto") == "legacy-encrypted-secret"


def test_rotation_reencrypts_with_new_key(credential_environment):
    tmp_path, _ = credential_environment
    store = _store(tmp_path)
    store.save_connection(store.SEED_USER_ID, "hashnode", "hash-secret")
    old = store._con.execute(
        "SELECT token FROM connections WHERE platform='hashnode'"
    ).fetchone()[0]

    new_key_id = rotate_file_key()
    assert store.reencrypt_connection_credentials() == 1
    new = store._con.execute(
        "SELECT token FROM connections WHERE platform='hashnode'"
    ).fetchone()[0]
    assert new != old
    assert new.startswith(f"enc:v1:{new_key_id}:")
    assert decrypt_token(new) == "hash-secret"


def test_wrong_key_fails_instead_of_returning_empty(credential_environment, monkeypatch):
    encrypted = encrypt_token("important-secret")
    monkeypatch.setenv("BLOGHUB_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("BLOGHUB_SECRET_KEY_ID", "wrong")
    configure_key_provider(None)
    with pytest.raises(CredentialDecryptionError):
        decrypt_token(encrypted)


def test_store_startup_fails_when_encrypted_key_is_unavailable(
    credential_environment, monkeypatch,
):
    tmp_path, _ = credential_environment
    store = _store(tmp_path)
    store.save_connection(store.SEED_USER_ID, "openai", "sk-important")
    store._con.close()

    monkeypatch.setenv("BLOGHUB_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("BLOGHUB_SECRET_KEY_ID", "replacement-without-previous")
    configure_key_provider(None)
    with pytest.raises(CredentialDecryptionError):
        _store(tmp_path)


def test_invalid_environment_key_fails_configuration(credential_environment, monkeypatch):
    monkeypatch.setenv("BLOGHUB_SECRET_KEY", "not-a-key")
    configure_key_provider(None)
    with pytest.raises(CredentialConfigurationError):
        get_key_provider()


@pytest.mark.parametrize(
    "value",
    [
        'Authorization: Bearer sk-test-secret',
        'api_key=sk-test-secret',
        '{"access_token":"oauth-secret","ok":true}',
        'Cookie: session=private; theme=dark',
        'auth_code=temporary-code',
    ],
)
def test_redaction_removes_secrets(value):
    redacted = redact_secrets(value)
    assert "secret" not in redacted
    assert "temporary-code" not in redacted
    assert "private" not in redacted
    assert "[REDACTED]" in redacted


def test_logging_filter_redacts_message_and_arguments():
    record = logging.LogRecord(
        "test", logging.INFO, __file__, 1,
        "request %s", ("Authorization: Bearer sk-log-secret",), None,
    )
    assert SecretRedactionFilter().filter(record)
    assert "sk-log-secret" not in record.getMessage()

    numeric_record = logging.LogRecord(
        "test", logging.INFO, __file__, 1, "status %d", (200,), None,
    )
    assert SecretRedactionFilter().filter(numeric_record)
    assert numeric_record.getMessage() == "status 200"
