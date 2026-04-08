"""
Token encryption/decryption using Fernet symmetric encryption.

Key is read from BLOGHUB_SECRET_KEY env var (URL-safe base64, 32 bytes).
Generate a key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Encrypted tokens are stored with a "fernet:" prefix so plaintext legacy
values continue to round-trip correctly without a migration step.

If BLOGHUB_SECRET_KEY is not set, tokens are stored and returned as
plaintext with a warning logged. Set the env var in production.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_PREFIX = "fernet:"

_fernet = None
_warned = False


def _get_fernet():
    global _fernet, _warned
    if _fernet is not None:
        return _fernet

    raw_key = os.environ.get("BLOGHUB_SECRET_KEY", "").strip()
    if not raw_key:
        if not _warned:
            logger.warning(
                "BLOGHUB_SECRET_KEY is not set. API tokens are stored in plaintext. "
                "Set this env var in production to encrypt tokens at rest."
            )
            _warned = True
        return None

    from cryptography.fernet import Fernet, InvalidToken  # noqa: F401
    try:
        _fernet = Fernet(raw_key.encode())
    except Exception:
        logger.error(
            "BLOGHUB_SECRET_KEY is set but is not a valid Fernet key. "
            "Tokens will be stored in plaintext until the key is fixed."
        )
        return None

    return _fernet


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token. Returns 'fernet:<ciphertext>' or plaintext if key not set."""
    if not plaintext:
        return plaintext
    f = _get_fernet()
    if f is None:
        return plaintext
    ciphertext = f.encrypt(plaintext.encode()).decode()
    return f"{_PREFIX}{ciphertext}"


def decrypt_token(stored: str) -> str:
    """Decrypt a stored token. Handles both encrypted and legacy plaintext values."""
    if not stored:
        return stored
    if not stored.startswith(_PREFIX):
        # Legacy plaintext value — return as-is.
        return stored
    f = _get_fernet()
    if f is None:
        logger.error(
            "Token is encrypted but BLOGHUB_SECRET_KEY is not set. Cannot decrypt."
        )
        return ""
    from cryptography.fernet import InvalidToken
    try:
        return f.decrypt(stored[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        logger.error("Token decryption failed. Key may have changed.")
        return ""
