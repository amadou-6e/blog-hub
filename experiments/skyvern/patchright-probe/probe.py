"""Open Hashnode's login checkpoint with a headed Patchright Chrome profile."""

import json
import os
from pathlib import Path

from patchright.sync_api import sync_playwright


ARTIFACT_DIR = Path(os.environ.get("PROBE_ARTIFACT_DIR", "/artifacts"))
PROFILE_DIR = Path(os.environ.get("PROBE_PROFILE_DIR", "/profile"))
TARGET_URL = os.environ.get("PROBE_URL", "https://hashnode.com/login")
EXECUTABLE_PATH = os.environ.get("PROBE_EXECUTABLE_PATH")


def classify(page_text: str, final_url: str, title: str) -> str:
    normalized = page_text.lower()
    if "failed to verify your browser" in normalized:
        return "blocked_browser_verification"
    if "vercel security checkpoint" in normalized:
        return "blocked_security_checkpoint"
    if any(
        marker in normalized
        for marker in (
            "continue with github",
            "continue with google",
            "sign in with github",
            "sign in with google",
        )
    ):
        return "login_available"
    if title.lower().startswith("log in") and "hashnode" in title.lower():
        return "login_available"
    if "/login" not in final_url:
        return "redirected_without_checkpoint"
    return "unknown"


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser_options = {
            "user_data_dir": PROFILE_DIR,
            "headless": False,
            "no_viewport": True,
        }
        if EXECUTABLE_PATH:
            browser_options["executable_path"] = EXECUTABLE_PATH
        else:
            browser_options["channel"] = "chrome"
        context = playwright.chromium.launch_persistent_context(
            **browser_options,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(15_000)

        page_text = page.locator("body").inner_text(timeout=15_000)
        title = page.title()
        result = {
            "classification": classify(page_text, page.url, title),
            "final_url": page.url,
            "title": title,
            "browser_mode": "custom_executable" if EXECUTABLE_PATH else "chrome",
        }
        page.screenshot(path=ARTIFACT_DIR / "hashnode-login.png", full_page=True)
        (ARTIFACT_DIR / "result.json").write_text(
            json.dumps(result, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result), flush=True)
        context.close()


if __name__ == "__main__":
    main()
