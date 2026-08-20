"""Core-owned Playwright runtime for trusted blog operation adapters."""
from __future__ import annotations

from pathlib import Path

from .contracts import BlogExtension, Capability, OperationNotSupported, OperationRequest


def execute_operation(
    extension: BlogExtension,
    *,
    profile_dir: Path,
    operation: Capability,
    request: OperationRequest,
) -> dict:
    if operation not in extension.manifest.capabilities:
        raise OperationNotSupported(extension.manifest.platform, operation.value)

    from patchright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir),
            headless=True,
            viewport={"width": 1440, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            return extension.operations.execute(page, operation, request)
        finally:
            context.close()
