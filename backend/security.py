"""Helpers that keep credentials out of application logs."""
from __future__ import annotations

import logging
import re
from typing import Any

_REDACTIONS = (
    re.compile(r'(?i)("(?:access_token|refresh_token|token|code|cookie|set-cookie|api_key|client_secret|password|session|authorization|proxy_authorization)"\s*:\s*")[^"]*(")'),
    re.compile(r"(?i)((?:authorization|proxy-authorization)\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+"),
    re.compile(r"(?i)((?:api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|auth[-_ ]?code|client[-_ ]?secret|password|session|token)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)([?&](?:code|state|token)=)[^&#\s]+"),
    re.compile(r"(?i)((?:cookie|set-cookie)\s*[:=]\s*)[^\r\n]+"),
    re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[opsu]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})\b"),
)


def redact_secrets(value: Any) -> str:
    redacted = str(value)
    for pattern in _REDACTIONS:
        if pattern.groups == 2:
            replacement = r"\1[REDACTED]\2"
        elif pattern.groups == 1:
            replacement = r"\1[REDACTED]"
        else:
            replacement = "[REDACTED]"
        redacted = pattern.sub(replacement, redacted)
    return redacted


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        _redact_record(record)
        return True


def _redact_record(record: logging.LogRecord) -> None:
    record.msg = redact_secrets(record.msg)
    if record.args:
        if isinstance(record.args, dict):
            record.args = {
                key: redact_secrets(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        else:
            record.args = tuple(
                redact_secrets(value) if isinstance(value, str) else value
                for value in record.args
            )


def install_secret_redaction() -> None:
    current_factory = logging.getLogRecordFactory()
    if getattr(current_factory, "_bloghub_redacts_secrets", False):
        return

    def redacting_factory(*args, **kwargs):
        record = current_factory(*args, **kwargs)
        _redact_record(record)
        return record

    redacting_factory._bloghub_redacts_secrets = True
    logging.setLogRecordFactory(redacting_factory)
