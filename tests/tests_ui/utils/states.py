"""
tests/tests_ui/utils/states.py
──────────────────────────────
Named screen-state assertions for all blog-hub UI screens.

Each ScreenState encodes the DOM truth for a specific named UI state:
  visible  — selectors that must be visible
  hidden   — selectors that must NOT be visible
  enabled  — interactive elements that must be enabled
  disabled — interactive elements that must be disabled
  text     — (selector, substring) pairs that must match

All assertions use Playwright's auto-retrying expect() — no manual
wait_for_timeout or wait_for_selector needed alongside these.

Usage
-----
from tests.tests_ui.utils.states import create_step_1, settings_platforms_tab

# Assert state before screenshotting (in visual tests)
from tests.tests_ui.utils.screenshots import assert_then_snap
assert_then_snap(page, create_step_1, "create_article", "step1_empty")

# Assert expected end-state after an action sequence (in breaking tests)
create_step_1.assert_on(page)
"""
from __future__ import annotations

from dataclasses import dataclass

from playwright.sync_api import Page, expect


@dataclass(frozen=True)
class ScreenState:
    """Declarative DOM-truth assertion for a named UI state."""

    visible: tuple[str, ...] = ()
    hidden: tuple[str, ...] = ()
    enabled: tuple[str, ...] = ()
    disabled: tuple[str, ...] = ()
    text: tuple[tuple[str, str], ...] = ()

    def assert_on(self, page: Page, *, timeout: int = 5000) -> None:
        """Assert all conditions hold using Playwright's auto-retrying expect()."""
        for sel in self.visible:
            expect(page.locator(sel)).to_be_visible(timeout=timeout)
        for sel in self.hidden:
            expect(page.locator(sel)).not_to_be_visible(timeout=timeout)
        for sel in self.enabled:
            expect(page.locator(sel)).to_be_enabled(timeout=timeout)
        for sel in self.disabled:
            expect(page.locator(sel)).to_be_disabled(timeout=timeout)
        for sel, txt in self.text:
            expect(page.locator(sel)).to_contain_text(txt, timeout=timeout)


# ── create_article  (screens/create-article/v1.html) ─────────────────────────

create_step_1 = ScreenState(
    visible=("#step-1", "#next-btn", "#prompt-text"),
    hidden=("#step-2", "#step-3"),
)

create_step_2 = ScreenState(
    visible=("#step-2", "#skill-list", "#next-btn", "#back-btn"),
    hidden=("#step-1", "#step-3"),
)

create_step_3 = ScreenState(
    visible=("#step-3", "#back-btn"),
    hidden=("#step-1", "#step-2"),
)

# ── overview  (screens/overview/v3.html) ──────────────────────────────────────

overview_idle = ScreenState(
    visible=("#create-menu-btn",),
    hidden=("#import-menu",),
)

overview_articles_loaded = ScreenState(
    visible=("#create-menu-btn", ".article-card"),
    hidden=("#import-menu",),
)

overview_menu_open = ScreenState(visible=("#create-menu-btn", "#import-menu"),)

# ── editor  (screens/editor/v2.html) ──────────────────────────────────────────

editor_loaded = ScreenState(visible=("#raw-editor", "#panel-strip", "#panel-content"),)

editor_panel_collapsed = ScreenState(
    visible=("#raw-editor", "#panel-strip"),
    hidden=("#panel-content",),
)

editor_destinations_open = ScreenState(visible=("#raw-editor", "#abody-destinations"),)

editor_chat_open = ScreenState(visible=("#raw-editor", "#abody-chat"),)

editor_patches_open = ScreenState(visible=("#raw-editor", "#abody-patches"),)

# ── settings  (screens/settings/v2.html) ──────────────────────────────────────

settings_platforms_tab = ScreenState(
    visible=("#section-platforms",),
    hidden=("#section-ai",),
)

settings_ai_tab = ScreenState(
    visible=("#section-ai",),
    hidden=("#section-platforms",),
)

# ── import_article  (screens/import-article/v1.html) ──────────────────────────

import_step1_platform_grid = ScreenState(visible=("#platform-grid",),)

import_step2_draft_list = ScreenState(
    visible=(".draft-row",),
    hidden=("#platform-grid",),
)
