"""Exclusive leases and targeted logout for shared persisted browser profiles."""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable


class ProfileBusy(RuntimeError):
    """The shared profile is owned by another browser or operation."""

    def __init__(self):
        super().__init__("Browser profile is busy")


@contextmanager
def profile_lease(root: Path, profile_id: str, *, session_id: str | None = None):
    """Serialize all owners; persistent markers outlive runner processes.

    Lock files must never be removed: flock locks an inode, not a pathname.
    A marker with unknown ownership fails closed, including after a torn write.
    """
    if (
        not profile_id or Path(profile_id).name != profile_id
        or profile_id in {".", ".."}
    ):
        raise ValueError("Invalid profile lease id")
    directory = root / ".profile-leases"
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / f"{profile_id}.json"
    with (directory / f"{profile_id}.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProfileBusy() from exc
        try:
            if marker.exists():
                try:
                    owner = json.loads(marker.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    raise ProfileBusy() from None
                if (
                    not session_id or not isinstance(owner, dict)
                    or owner.get("session_id") != session_id
                ):
                    raise ProfileBusy()
            yield marker
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def persist_profile_lease(marker: Path, session_id: str | None) -> None:
    # Write before sending the create request: a timeout may still create a browser.
    temporary = marker.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump({"session_id": session_id}, output)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(marker)
    directory_fd = os.open(marker.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def local_profile_lease(profile_dir: Path):
    root = (
        profile_dir.parents[2]
        if profile_dir.parent.name == "profiles" else profile_dir.parent
    )
    return profile_lease(root, profile_dir.name)


def domain_matches(domain: object, session_domains: Iterable[str]) -> bool:
    candidate = str(domain or "").lstrip(".").lower()
    return any(
        candidate == allowed or candidate.endswith(f".{allowed}")
        for allowed in (item.lstrip(".").lower() for item in session_domains)
    )


def clear_context_session(context: Any, session_domains: tuple[str, ...]) -> int:
    removed = 0
    for cookie in context.cookies():
        if not domain_matches(cookie.get("domain"), session_domains):
            continue
        context.clear_cookies(
            name=cookie.get("name"),
            domain=cookie.get("domain"),
            path=cookie.get("path") or "/",
        )
        removed += 1
    return removed


def _clear_cookie_snapshot(
    profile_dir: Path, session_domains: tuple[str, ...],
) -> None:
    snapshot = profile_dir / ".skyvern_session_cookies.json"
    try:
        cookies = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return
    if not isinstance(cookies, list):
        return
    retained = [
        cookie for cookie in cookies
        if not isinstance(cookie, dict)
        or not domain_matches(cookie.get("domain"), session_domains)
    ]
    temporary = snapshot.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(retained, separators=(",", ":")), encoding="utf-8")
    temporary.replace(snapshot)


def clear_profile_session(
    profile_dir: Path, session_domains: tuple[str, ...],
) -> int:
    if not session_domains:
        raise ValueError("Browser extension does not declare a session domain")
    with local_profile_lease(profile_dir):
        return _clear_profile_session(profile_dir, session_domains)


def _clear_profile_session(profile_dir: Path, session_domains: tuple[str, ...]) -> int:
    if not profile_dir.is_dir():
        return 0

    from patchright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir), headless=True,
        )
        try:
            removed = clear_context_session(context, session_domains)
        finally:
            context.close()
    _clear_cookie_snapshot(profile_dir, session_domains)
    return removed
