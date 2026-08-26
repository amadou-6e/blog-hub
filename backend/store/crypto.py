"""Encryption-at-rest for provider credentials.

Ciphertext is versioned and identifies the key used to encrypt it.  Key
providers deliberately live outside SQLite so a database copy is insufficient
to recover credentials.
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from cryptography.fernet import Fernet, InvalidToken

_PREFIX = "enc:v1:"
_LEGACY_PREFIX = "fernet:"
_DEFAULT_KEY_FILE = Path(__file__).resolve().parents[2] / "data" / "credential-keys.json"


class CredentialConfigurationError(RuntimeError):
    """Credential key configuration is missing or invalid."""


class CredentialDecryptionError(RuntimeError):
    """A stored credential cannot be decrypted with the available keys."""


class KeyProvider(Protocol):
    """Hook for environment, file, KMS, Vault, or other key providers."""

    def active_key(self) -> tuple[str, bytes]: ...

    def keys(self) -> Mapping[str, bytes]: ...


def _validate_key(key: str | bytes, *, name: str) -> bytes:
    value = key.encode() if isinstance(key, str) else key
    try:
        Fernet(value)
    except (TypeError, ValueError) as exc:
        raise CredentialConfigurationError(f"{name} is not a valid Fernet key") from exc
    return value


@dataclass(frozen=True)
class StaticKeyProvider:
    """Simple provider suitable for environment variables and external adapters."""

    active_key_id: str
    keyring: Mapping[str, str | bytes]

    def keys(self) -> Mapping[str, bytes]:
        if any(not key_id or ":" in key_id for key_id in self.keyring):
            raise CredentialConfigurationError("credential key id is invalid")
        validated = {
            key_id: _validate_key(key, name=f"credential key {key_id!r}")
            for key_id, key in self.keyring.items()
        }
        if self.active_key_id not in validated:
            raise CredentialConfigurationError("active credential key is absent from keyring")
        return validated

    def active_key(self) -> tuple[str, bytes]:
        return self.active_key_id, self.keys()[self.active_key_id]


class FileKeyProvider:
    """Local keyring stored separately from the application database."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        if not self.path.exists():
            self._write_new_keyring()
        self._cached_mtime: float | None = None
        self._cached_keys: Mapping[str, bytes] | None = None
        self._cached_active: str | None = None

    def _read(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialConfigurationError(
                f"cannot read credential key file {self.path}"
            ) from exc
        if payload.get("version") != 1 or not isinstance(payload.get("keys"), dict):
            raise CredentialConfigurationError("credential key file has an unsupported format")
        return payload

    def _read_cached(self) -> tuple[str, Mapping[str, bytes]]:
        mtime = self.path.stat().st_mtime
        if self._cached_mtime != mtime:
            payload = self._read()
            self._cached_keys = StaticKeyProvider(payload.get("active", ""), payload["keys"]).keys()
            self._cached_active = payload.get("active", "")
            self._cached_mtime = mtime
        return self._cached_active, self._cached_keys

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _write_new_keyring(self) -> None:
        key_id = secrets.token_hex(8)
        payload = {
            "version": 1,
            "active": key_id,
            "keys": {key_id: Fernet.generate_key().decode()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, self.path)
            except FileExistsError:
                pass  # Another process won first-run initialization.
        finally:
            try:
                os.unlink(temporary)
            except OSError:
                pass

    def keys(self) -> Mapping[str, bytes]:
        _, keys = self._read_cached()
        return keys

    def active_key(self) -> tuple[str, bytes]:
        active, keys = self._read_cached()
        return active, keys[active]

    def rotate(self) -> str:
        payload = self._read()
        key_id = secrets.token_hex(8)
        payload["keys"][key_id] = Fernet.generate_key().decode()
        payload["active"] = key_id
        self._write(payload)
        self._cached_mtime = None
        return key_id

    def retire_inactive(self) -> int:
        """Remove retired keys after all credentials have been re-encrypted."""
        payload = self._read()
        active = payload["active"]
        removed = len(payload["keys"]) - 1
        payload["keys"] = {active: payload["keys"][active]}
        self._write(payload)
        self._cached_mtime = None
        return removed


_provider: KeyProvider | None = None


def _provider_from_environment() -> KeyProvider:
    active_key = os.environ.get("BLOGHUB_SECRET_KEY", "").strip()
    if active_key:
        active_id = os.environ.get("BLOGHUB_SECRET_KEY_ID", "primary").strip()
        previous_raw = os.environ.get("BLOGHUB_PREVIOUS_SECRET_KEYS", "{}").strip() or "{}"
        try:
            previous = json.loads(previous_raw)
        except json.JSONDecodeError as exc:
            raise CredentialConfigurationError(
                "BLOGHUB_PREVIOUS_SECRET_KEYS must be a JSON object of key ids to Fernet keys"
            ) from exc
        if not isinstance(previous, dict):
            raise CredentialConfigurationError("BLOGHUB_PREVIOUS_SECRET_KEYS must be a JSON object")
        return StaticKeyProvider(active_id, {**previous, active_id: active_key})

    key_file = os.environ.get("BLOGHUB_CREDENTIAL_KEY_FILE", "").strip()
    return FileKeyProvider(key_file or _DEFAULT_KEY_FILE)


def get_key_provider() -> KeyProvider:
    global _provider
    if _provider is None:
        _provider = _provider_from_environment()
        _provider.active_key()  # Validate eagerly; invalid configuration must fail startup.
    return _provider


def configure_key_provider(provider: KeyProvider | None) -> None:
    """Install an external key provider, or reset to configured defaults."""
    global _provider
    _provider = provider


def encrypt_token(plaintext: str) -> str:
    if not plaintext:
        return plaintext
    key_id, key = get_key_provider().active_key()
    ciphertext = Fernet(key).encrypt(plaintext.encode()).decode()
    return f"{_PREFIX}{key_id}:{ciphertext}"


def decrypt_token(stored: str) -> str:
    """Decrypt current or legacy ciphertext; plaintext is accepted for migration only."""
    if not stored:
        return stored
    keys = get_key_provider().keys()
    if stored.startswith(_PREFIX):
        remainder = stored[len(_PREFIX):]
        try:
            key_id, ciphertext = remainder.split(":", 1)
            key = keys[key_id]
            return Fernet(key).decrypt(ciphertext.encode()).decode()
        except (KeyError, ValueError, InvalidToken, UnicodeDecodeError) as exc:
            raise CredentialDecryptionError(
                "stored credential cannot be decrypted; restore its key or reconnect"
            ) from exc
    if stored.startswith(_LEGACY_PREFIX):
        ciphertext = stored[len(_LEGACY_PREFIX):].encode()
        for key in keys.values():
            try:
                return Fernet(key).decrypt(ciphertext).decode()
            except (InvalidToken, UnicodeDecodeError):
                continue
        raise CredentialDecryptionError(
            "legacy credential cannot be decrypted; restore its key or reconnect"
        )
    return stored


def needs_reencryption(stored: str) -> bool:
    if not stored:
        return False
    active_id, _ = get_key_provider().active_key()
    return not stored.startswith(f"{_PREFIX}{active_id}:")


def rotate_file_key() -> str:
    provider = get_key_provider()
    if not isinstance(provider, FileKeyProvider):
        raise CredentialConfigurationError(
            "key rotation is managed by the configured external key provider"
        )
    return provider.rotate()


def retire_inactive_file_keys() -> int:
    provider = get_key_provider()
    if not isinstance(provider, FileKeyProvider):
        raise CredentialConfigurationError(
            "key retirement is managed by the configured external key provider"
        )
    return provider.retire_inactive()
