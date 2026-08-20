"""Apply the minimal Patchright experiment to the pinned Skyvern source tree."""

from pathlib import Path


SKYVERN_ROOT = Path("/app/skyvern")
BROWSER_FACTORY = SKYVERN_ROOT / "webeye/browser_factory.py"
SCREENCAST = SKYVERN_ROOT / "forge/sdk/routes/streaming/screencast.py"
CDP_INPUT = SKYVERN_ROOT / "forge/sdk/routes/streaming/cdp_input.py"
REAL_BROWSER_STATE = SKYVERN_ROOT / "webeye/real_browser_state.py"
PERSISTENT_SESSIONS_MANAGER = SKYVERN_ROOT / "webeye/default_persistent_sessions_manager.py"


def rewrite_imports() -> int:
    changed = 0
    for path in SKYVERN_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        patched = source.replace("from playwright", "from patchright")
        if patched != source:
            path.write_text(patched, encoding="utf-8")
            changed += 1
    return changed


def add_browser_executable() -> None:
    source = BROWSER_FACTORY.read_text(encoding="utf-8")
    headful_launch_anchor = '''    browser_args = BrowserContextFactory.build_browser_args(
        proxy_location=proxy_location, cdp_port=cdp_port, extra_http_headers=extra_http_headers
    )
    browser_args.update(
        {
            "user_data_dir": user_data_dir,
            "downloads_path": download_dir,
            "headless": False,
        }
    )
'''
    headful_launch_replacement = '''    # Match Patchright's minimal persistent-context configuration. Skyvern's
    # HAR/video/viewport bundle closes this pinned browser during Page.enable.
    browser_args = {
        "user_data_dir": user_data_dir,
        "downloads_path": download_dir,
        "headless": False,
        "no_viewport": True,
        # Chromium stalls for roughly 40 seconds while probing unavailable GPU
        # support under Docker/Xvfb. Skip that probe and render in software.
        "args": ["--window-size=1180,820", "--disable-gpu"],
    }
    if settings.CHROME_EXECUTABLE_PATH:
        browser_args["executable_path"] = settings.CHROME_EXECUTABLE_PATH
'''
    headless_anchor = '''        }
    )

    browser_artifacts = BrowserContextFactory.build_browser_artifacts(
'''
    executable_assignment = '''        }
    )
    if settings.CHROME_EXECUTABLE_PATH:
        browser_args["executable_path"] = settings.CHROME_EXECUTABLE_PATH

    browser_artifacts = BrowserContextFactory.build_browser_artifacts(
'''
    if source.count(headful_launch_anchor) != 1:
        raise RuntimeError("Pinned headful browser-factory launch block changed")
    source = source.replace(headful_launch_anchor, headful_launch_replacement)
    before_headful, headful_and_after = source.split(headful_launch_replacement, 1)
    har_anchor = 'har_path=browser_args["record_har_path"]'
    if har_anchor not in headful_and_after:
        raise RuntimeError("Pinned headful HAR artifact anchor changed")
    headful_and_after = headful_and_after.replace(har_anchor, "har_path=None", 1)
    source = before_headful + headful_launch_replacement + headful_and_after
    if source.count(headless_anchor) != 1:
        raise RuntimeError("Pinned headless browser-factory anchor changed")
    source = source.replace(headless_anchor, executable_assignment)
    BROWSER_FACTORY.write_text(source, encoding="utf-8")


def improve_local_stream_quality() -> None:
    source = SCREENCAST.read_text(encoding="utf-8")
    dimensions = "DEFAULT_WIDTH = 1280\nDEFAULT_HEIGHT = 720"
    if source.count(dimensions) != 1:
        raise RuntimeError("Pinned screencast dimensions changed")
    source = source.replace(
        dimensions,
        "DEFAULT_WIDTH = 1920\nDEFAULT_HEIGHT = 1200",
    )
    scale_registry_anchor = "ACTIVE_PAGE_POLL_INTERVAL = 0.5\n"
    scale_registry = scale_registry_anchor + '''
_viewer_device_scales: dict[str, float] = {}


def set_viewer_device_scale(entity_id: str, scale: float) -> None:
    _viewer_device_scales[entity_id] = max(1.0, min(float(scale), 3.0))
'''
    if source.count(scale_registry_anchor) != 1:
        raise RuntimeError("Pinned screencast scale registry anchor changed")
    source = source.replace(scale_registry_anchor, scale_registry)
    if source.count('"format": "jpeg"') != 3 or source.count('"quality": 60') != 2:
        raise RuntimeError("Pinned screencast format settings changed")
    source = source.replace('"format": "jpeg"', '"format": "png"')
    source = source.replace('                    "quality": 60,\n', "")

    state_anchor = '''    viewport_info: dict[str, int] = {"width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT}
'''
    state_replacement = state_anchor + '''    hidpi_capture_in_flight = False
    last_hidpi_capture_at = 0.0
    hashnode_login_streak = 0
    hashnode_login_complete = False
'''
    if source.count(state_anchor) != 1:
        raise RuntimeError("Pinned screencast state anchor changed")
    source = source.replace(state_anchor, state_replacement)

    frame_anchor = '''    async def _on_frame(session: CDPSession, params: dict) -> None:
        if session is not cdp_session:
            return
        data = params.get("data", "")
        session_id = params.get("sessionId", 0)
        metadata = params.get("metadata", {})
        if metadata:
            _update_viewport_from_metadata(metadata)
        asyncio.create_task(_ack_frame(session, session_id))
        _queue_frame(data)
'''
    frame_replacement = '''    async def _capture_hidpi_frame(session: CDPSession) -> None:
        nonlocal hidpi_capture_in_flight
        try:
            metrics = await session.send("Page.getLayoutMetrics", {})
            viewport = metrics.get("cssVisualViewport") or metrics.get("visualViewport") or {}
            width = viewport.get("clientWidth")
            height = viewport.get("clientHeight")
            if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
                return
            result = await session.send(
                "Page.captureScreenshot",
                {
                    "format": "png",
                    "captureBeyondViewport": False,
                    "optimizeForSpeed": True,
                    "clip": {
                        "x": viewport.get("pageX", 0),
                        "y": viewport.get("pageY", 0),
                        "width": width,
                        "height": height,
                        "scale": _viewer_device_scales.get(entity_id, 1.0),
                    },
                },
            )
            _queue_frame(result.get("data", ""))
        except Exception:
            LOG.debug("Could not capture HiDPI screencast frame", exc_info=True)
        finally:
            hidpi_capture_in_flight = False

    async def _on_frame(session: CDPSession, params: dict) -> None:
        nonlocal hidpi_capture_in_flight, last_hidpi_capture_at
        if session is not cdp_session:
            return
        data = params.get("data", "")
        session_id = params.get("sessionId", 0)
        metadata = params.get("metadata", {})
        if metadata:
            _update_viewport_from_metadata(metadata)
        asyncio.create_task(_ack_frame(session, session_id))
        now = asyncio.get_running_loop().time()
        # captureScreenshot itself can emit a screencast frame. Suppress that
        # feedback and cap expensive lossless HiDPI captures at two per second.
        if hidpi_capture_in_flight or now - last_hidpi_capture_at < 0.5:
            return
        last_hidpi_capture_at = now
        hidpi_capture_in_flight = True
        asyncio.create_task(_capture_hidpi_frame(session))
'''
    if source.count(frame_anchor) != 1:
        raise RuntimeError("Pinned screencast frame handler changed")
    source = source.replace(frame_anchor, frame_replacement)

    stop_anchor = '''        try:
            await session.send("Page.stopScreencast", {})
        except Exception:
            pass
        try:
            await session.detach()
'''
    stop_replacement = '''        try:
            await session.detach()
'''
    if source.count(stop_anchor) != 1:
        raise RuntimeError("Pinned screencast cleanup changed")
    source = source.replace(stop_anchor, stop_replacement)

    attach_anchor = '''        next_session.on("Page.screencastFrame", lambda params: asyncio.create_task(_on_frame(next_session, params)))
        try:
            await next_session.send(
                "Page.startScreencast",
                {
                    "format": "png",
                    "maxWidth": DEFAULT_WIDTH,
                    "maxHeight": DEFAULT_HEIGHT,
                },
            )
        except (asyncio.CancelledError, Exception):
            await _stop_current_screencast()
            raise
        attached_page = page
        await _prime_current_frame(next_session, page)
        LOG.info(
            "CDP screencast started",
            entity_id=entity_id,
            entity_type=entity_type,
            url=getattr(page, "url", ""),
        )
'''
    attach_replacement = '''        attached_page = page
        await _prime_current_frame(next_session, page)
        LOG.info(
            "CDP screenshot stream started",
            entity_id=entity_id,
            entity_type=entity_type,
            url=getattr(page, "url", ""),
        )
'''
    if source.count(attach_anchor) != 1:
        raise RuntimeError("Pinned screencast attachment changed")
    source = source.replace(attach_anchor, attach_replacement)

    forwarding_anchor = '''    async def _frame_forwarding_loop() -> None:
'''
    capture_loop = '''    async def _refresh_hashnode_login_state() -> None:
        nonlocal hashnode_login_streak, hashnode_login_complete
        page = attached_page
        if entity_type != "browser_session" or page is None:
            hashnode_login_streak = 0
            hashnode_login_complete = False
            return
        try:
            cookies = await page.context.cookies(["https://hashnode.com/"])
            authenticated = any(
                bool(cookie.get("value"))
                and (
                    cookie.get("name") in {"authjs.session-token", "hashnode-session"}
                    or str(cookie.get("name", "")).startswith("__Secure-authjs.session-token")
                )
                for cookie in cookies
            )
        except Exception:
            authenticated = False
        hashnode_login_streak = hashnode_login_streak + 1 if authenticated else 0
        # OAuth callbacks can briefly expose a session cookie before the app
        # rejects it. Require a sustained authenticated state before replacing
        # the browser with BlogHub's success message.
        current_url = str(getattr(page, "url", "") or "").lower()
        outside_login = not any(part in current_url for part in ("/login", "/signin", "/onboard"))
        hashnode_login_complete = hashnode_login_streak >= 20 and outside_login

    async def _capture_polling_loop() -> None:
        while True:
            session = cdp_session
            if session is not None:
                await _capture_hidpi_frame(session)
            await _refresh_hashnode_login_state()
            await asyncio.sleep(0.5)

'''
    if source.count(forwarding_anchor) != 1:
        raise RuntimeError("Pinned frame forwarding loop changed")
    source = source.replace(forwarding_anchor, capture_loop + forwarding_anchor)

    url_anchor = '''                try:
                    current_url = getattr(attached_page, "url", "") or ""
                except Exception:
                    pass
'''
    url_replacement = url_anchor + '''            if hashnode_login_complete and current_url.startswith(
                ("https://hashnode.com/", "https://www.hashnode.com/")
            ):
                current_url = current_url.split("#", 1)[0] + "#bloghub-authenticated"
'''
    if source.count(url_anchor) != 1:
        raise RuntimeError("Pinned screencast URL forwarding changed")
    source = source.replace(url_anchor, url_replacement)

    task_anchor = '''        forward_task = asyncio.create_task(_frame_forwarding_loop())
        poll_task = asyncio.create_task(_completion_polling_loop())
        page_monitor_task = asyncio.create_task(_active_page_monitor_loop())

        done, pending = await asyncio.wait(
            [forward_task, poll_task, page_monitor_task],
'''
    task_replacement = '''        capture_task = asyncio.create_task(_capture_polling_loop())
        forward_task = asyncio.create_task(_frame_forwarding_loop())
        poll_task = asyncio.create_task(_completion_polling_loop())
        page_monitor_task = asyncio.create_task(_active_page_monitor_loop())

        done, pending = await asyncio.wait(
            [capture_task, forward_task, poll_task, page_monitor_task],
'''
    if source.count(task_anchor) != 1:
        raise RuntimeError("Pinned screencast task group changed")
    source = source.replace(task_anchor, task_replacement)
    SCREENCAST.write_text(source, encoding="utf-8")


def add_viewport_sync() -> None:
    source = CDP_INPUT.read_text(encoding="utf-8")
    import_anchor = '''    release_browser_state,
    wait_for_browser_state,
)'''
    import_replacement = '''    release_browser_state,
    set_viewer_device_scale,
    wait_for_browser_state,
)'''
    if source.count(import_anchor) != 1:
        raise RuntimeError("Pinned CDP input screencast imports changed")
    source = source.replace(import_anchor, import_replacement)

    constants_anchor = "_MAX_URL_LEN = 2083\nACTIVE_PAGE_INPUT_REFRESH_INTERVAL = 0.5"
    constants_replacement = """_MAX_URL_LEN = 2083
_MIN_VIEWPORT_WIDTH = 320
_MAX_VIEWPORT_WIDTH = 2560
_MIN_VIEWPORT_HEIGHT = 240
_MAX_VIEWPORT_HEIGHT = 1600
_MIN_DEVICE_SCALE_FACTOR = 0.5
_MAX_DEVICE_SCALE_FACTOR = 3.0
ACTIVE_PAGE_INPUT_REFRESH_INTERVAL = 0.5"""
    if source.count(constants_anchor) != 1:
        raise RuntimeError("Pinned CDP input constants changed")
    source = source.replace(constants_anchor, constants_replacement)

    validator_anchor = "\n\nasync def _close_ws_safely("
    validator = '''

def _validate_viewport_event(msg: dict) -> dict | None:
    width = msg.get("width")
    height = msg.get("height")
    scale = msg.get("deviceScaleFactor", 1)
    if type(width) not in (int, float) or type(height) not in (int, float):
        return None
    if type(scale) not in (int, float):
        return None
    return {
        "width": max(_MIN_VIEWPORT_WIDTH, min(round(width), _MAX_VIEWPORT_WIDTH)),
        "height": max(_MIN_VIEWPORT_HEIGHT, min(round(height), _MAX_VIEWPORT_HEIGHT)),
        "deviceScaleFactor": max(
            _MIN_DEVICE_SCALE_FACTOR,
            min(float(scale), _MAX_DEVICE_SCALE_FACTOR),
        ),
        "mobile": False,
    }
'''
    if source.count(validator_anchor) != 1:
        raise RuntimeError("Pinned CDP input validator anchor changed")
    source = source.replace(validator_anchor, validator + validator_anchor)

    dispatch_anchor = '''    if kind == "navigateEvent":
        await _dispatch_navigate_event(page, msg, log_id_key, log_id_value, websocket)
        return
'''
    dispatch_replacement = '''    if kind == "viewportEvent":
        viewport = _validate_viewport_event(msg)
        if viewport is None:
            LOG.warning("CDP input: viewport validation failed", **{log_id_key: log_id_value})
            return
        await cdp_session.send("Emulation.setDeviceMetricsOverride", viewport)
        set_viewer_device_scale(log_id_value, viewport["deviceScaleFactor"])
        LOG.info("CDP input: viewport synchronized", **{log_id_key: log_id_value}, **viewport)
        return

''' + dispatch_anchor
    if source.count(dispatch_anchor) != 1:
        raise RuntimeError("Pinned CDP input dispatch anchor changed")
    source = source.replace(dispatch_anchor, dispatch_replacement)

    control_anchor = '        if channel.interactor != "user":\n'
    if source.count(control_anchor) != 1:
        raise RuntimeError("Pinned CDP input control gate changed")
    source = source.replace(
        control_anchor,
        '        if channel.interactor != "user" and kind != "viewportEvent":\n',
    )

    viewport_state_anchor = '''        self.page_resolution_failed = False

    async def get_session'''
    viewport_state_replacement = '''        self.page_resolution_failed = False
        self.viewport: dict | None = None

    async def get_session'''
    if source.count(viewport_state_anchor) != 1:
        raise RuntimeError("Pinned CDP input session state changed")
    source = source.replace(viewport_state_anchor, viewport_state_replacement)

    page_rebind_anchor = '''        self.cdp_session = session
        self.page = page
        LOG.info(
'''
    page_rebind_replacement = '''        self.cdp_session = session
        self.page = page
        if self.viewport is not None:
            await session.send("Emulation.setDeviceMetricsOverride", self.viewport)
        LOG.info(
'''
    if source.count(page_rebind_anchor) != 1:
        raise RuntimeError("Pinned CDP input page rebind changed")
    source = source.replace(page_rebind_anchor, page_rebind_replacement)

    dispatch_signature_anchor = '''async def _dispatch_event(
    cdp_session: CDPSession,
    page: object,
'''
    dispatch_signature_replacement = '''async def _dispatch_event(
    cdp_session: CDPSession,
    input_session: ActivePageCdpInputSession,
    page: object,
'''
    if source.count(dispatch_signature_anchor) != 1:
        raise RuntimeError("Pinned CDP event dispatch signature changed")
    source = source.replace(dispatch_signature_anchor, dispatch_signature_replacement)

    viewport_dispatch_anchor = '''        await cdp_session.send("Emulation.setDeviceMetricsOverride", viewport)
        set_viewer_device_scale(log_id_value, viewport["deviceScaleFactor"])
'''
    viewport_dispatch_replacement = '''        input_session.viewport = viewport
        await cdp_session.send("Emulation.setDeviceMetricsOverride", viewport)
        set_viewer_device_scale(log_id_value, viewport["deviceScaleFactor"])
'''
    if source.count(viewport_dispatch_anchor) != 1:
        raise RuntimeError("Pinned CDP viewport dispatch changed")
    source = source.replace(viewport_dispatch_anchor, viewport_dispatch_replacement)

    dispatch_call_anchor = '''            await _dispatch_event(cdp_session, input_session.page, kind, msg, log_id_key, log_id_value, websocket)'''
    dispatch_call_replacement = '''            await _dispatch_event(cdp_session, input_session, input_session.page, kind, msg, log_id_key, log_id_value, websocket)'''
    if source.count(dispatch_call_anchor) != 1:
        raise RuntimeError("Pinned CDP event dispatch call changed")
    source = source.replace(dispatch_call_anchor, dispatch_call_replacement)
    CDP_INPUT.write_text(source, encoding="utf-8")


def recover_streaming_page() -> None:
    source = REAL_BROWSER_STATE.read_text(encoding="utf-8")
    missing_page_anchor = '''        if len(pages) == 0:
            LOG.info("No http, https or blank page found in the browser context, return None")
            return None
'''
    missing_page_replacement = '''        if len(pages) == 0:
            LOG.info("No active page found in the browser context; attempting recovery")
            return await self._reopen_lost_working_page()
'''
    if source.count(missing_page_anchor) != 1:
        raise RuntimeError("Pinned missing-page handling changed")
    source = source.replace(missing_page_anchor, missing_page_replacement)
    REAL_BROWSER_STATE.write_text(source, encoding="utf-8")


def preserve_reused_browser_profile() -> None:
    source = PERSISTENT_SESSIONS_MANAGER.read_text(encoding="utf-8")
    artifacts_anchor = '''        browser_artifacts = browser_session.browser_state.browser_artifacts
        if export_profile is not False and browser_artifacts and browser_artifacts.browser_session_dir:
'''
    artifacts_replacement = '''        browser_artifacts = browser_session.browser_state.browser_artifacts
        browser_closed_before_export = False
        if export_profile is not False and browser_artifacts and browser_artifacts.browser_session_dir:
'''
    if source.count(artifacts_anchor) != 1:
        raise RuntimeError("Pinned browser-profile artifact setup changed")
    source = source.replace(artifacts_anchor, artifacts_replacement)

    snapshot_anchor = '''            await persist_session_cookies(
                browser_session.browser_state.browser_context, browser_artifacts.browser_session_dir
            )
            if export_profile is None:
'''
    snapshot_replacement = '''            await persist_session_cookies(
                browser_session.browser_state.browser_context, browser_artifacts.browser_session_dir
            )
            # Chromium may not flush newly issued persistent cookies to SQLite
            # until its context closes. Export only after that flush completes.
            try:
                await browser_session.browser_state.close()
                browser_closed_before_export = True
            except TargetClosedError:
                browser_closed_before_export = True
                LOG.info(
                    "Browser context already closed before profile export",
                    organization_id=organization_id,
                    session_id=browser_session_id,
                )
            except Exception:
                LOG.warning(
                    "Error closing browser before profile export; retrying after export",
                    organization_id=organization_id,
                    session_id=browser_session_id,
                    exc_info=True,
                )
            if export_profile is None:
'''
    if source.count(snapshot_anchor) != 1:
        raise RuntimeError("Pinned browser-profile cookie snapshot changed")
    source = source.replace(snapshot_anchor, snapshot_replacement)

    final_close_anchor = '''        try:
            await browser_session.browser_state.close()
        except TargetClosedError:
            LOG.info(
                "Browser context already closed",
                organization_id=organization_id,
                session_id=browser_session_id,
            )
        except Exception:
            LOG.warning(
                "Error while closing browser session",
                organization_id=organization_id,
                session_id=browser_session_id,
                exc_info=True,
            )
'''
    final_close_replacement = '''        if not browser_closed_before_export:
            try:
                await browser_session.browser_state.close()
            except TargetClosedError:
                LOG.info(
                    "Browser context already closed",
                    organization_id=organization_id,
                    session_id=browser_session_id,
                )
            except Exception:
                LOG.warning(
                    "Error while closing browser session",
                    organization_id=organization_id,
                    session_id=browser_session_id,
                    exc_info=True,
                )
'''
    if source.count(final_close_anchor) != 1:
        raise RuntimeError("Pinned final browser close block changed")
    source = source.replace(final_close_anchor, final_close_replacement)

    profile_id_anchor = '''                        profile_id=browser_session_id,
                        directory=browser_artifacts.browser_session_dir,
'''
    profile_id_replacement = '''                        # A reused session must update the profile it loaded. Saving it
                        # under the transient session ID loses new authentication state.
                        profile_id=browser_artifacts.applied_browser_profile_id or browser_session_id,
                        directory=browser_artifacts.browser_session_dir,
'''
    if source.count(profile_id_anchor) != 1:
        raise RuntimeError("Pinned browser-profile export destination changed")
    source = source.replace(profile_id_anchor, profile_id_replacement)
    PERSISTENT_SESSIONS_MANAGER.write_text(source, encoding="utf-8")


def main() -> None:
    changed = rewrite_imports()
    if changed < 50:
        raise RuntimeError(f"Expected at least 50 Playwright import files, found {changed}")
    add_browser_executable()
    improve_local_stream_quality()
    add_viewport_sync()
    recover_streaming_page()
    preserve_reused_browser_profile()
    print(f"Rewrote Playwright imports in {changed} Skyvern files")


if __name__ == "__main__":
    main()
