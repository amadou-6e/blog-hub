"""
tests/tests_ui/utils/screenshots.py
────────────────────────────────────
Shared screenshot helpers for visual and breaking-path tests.

All outputs land under:
    tests/tests_ui/outputs/screenshots/<screen>/<state>.png

Usage
-----
from tests.tests_ui.utils.screenshots import snap, snap_element, snap_states

snap(page, "overview", "empty_store")
snap_element(page.locator(".article-card").first, "overview", "card_hover")
snap_states(page, "settings", [
    ("platforms_tab",      lambda: None),
    ("ai_tab",             lambda: page.get_by_role("button", name="AI Providers").click()),
])
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from tests.tests_ui.utils.states import ScreenState

# Root of the outputs tree — anchored to this file's location
_OUTPUTS_ROOT = Path(__file__).resolve().parents[1] / "outputs" / "screenshots"


def _dir(screen: str) -> Path:
    d = _OUTPUTS_ROOT / screen
    d.mkdir(parents=True, exist_ok=True)
    return d


def snap(page, screen: str, state: str) -> Path:
    """Full-page screenshot of the current page state.

    Parameters
    ----------
    page:   Playwright Page object
    screen: logical screen name used as the sub-directory  (e.g. "overview")
    state:  descriptive state label used as the filename   (e.g. "empty_store")

    Returns the Path where the PNG was saved.
    """
    path = _dir(screen) / f"{state}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


def snap_element(locator, screen: str, state: str) -> Path:
    """Screenshot of a single element (clipped to its bounding box).

    Parameters
    ----------
    locator: Playwright Locator
    screen:  logical screen name
    state:   descriptive state label

    Returns the Path where the PNG was saved.
    """
    path = _dir(screen) / f"{state}.png"
    locator.screenshot(path=str(path))
    return path


def snap_states(
    page,
    screen: str,
    states: list[tuple[str, Callable[[], None]]],
    *,
    settle_ms: int = 200,
) -> list[Path]:
    """Apply a series of state-setup callbacks and screenshot after each.

    Parameters
    ----------
    page:      Playwright Page object
    screen:    logical screen name (shared sub-directory)
    states:    list of (state_label, setup_callable) — setup is called before screenshot
    settle_ms: ms to wait after each setup before screenshotting (default 200)

    Returns a list of saved Paths, one per state.
    """
    paths = []
    for label, setup in states:
        setup()
        if settle_ms:
            page.wait_for_timeout(settle_ms)
        paths.append(snap(page, screen, label))
    return paths


def assert_then_snap(page, state: "ScreenState", screen: str, label: str) -> Path:
    """Assert the page is in the expected state, then take a full-page screenshot.

    Combines a ScreenState assertion (auto-retrying expect() calls) with snap()
    so screenshots are only captured when the UI is confirmed to be correct.

    Parameters
    ----------
    page:   Playwright Page object
    state:  ScreenState whose assertions must pass before screenshotting
    screen: logical screen name used as the sub-directory
    label:  descriptive state label used as the filename

    Returns the Path where the PNG was saved.
    """
    state.assert_on(page)
    return snap(page, screen, label)
