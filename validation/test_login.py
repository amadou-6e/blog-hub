"""Real Settings -> backend -> runner -> Skyvern -> local identity flows.

No route interception, patched authentication, or external provider credentials.
Mouse events use the production CDP input channel and fixed fixture geometry.
"""
import json
import secrets
import ssl
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
import pytest
from playwright.sync_api import sync_playwright, expect
from websockets.sync.client import connect
from skyvern_browser import _api_key

BACKEND = 'http://backend:8000'
CONNECTION = BACKEND + '/api/connections/medium/browser-connection'


def request(method, url, **kwargs):
    response = httpx.request(method, url, timeout=120, **kwargs)
    response.raise_for_status()
    return response.json()


def control(**kwargs):
    return request('POST', 'https://fixture.test/control',
                   verify=ssl.create_default_context(cafile='/certs/ca.crt'), json=kwargs)


def eventually(check, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = check()
        if last:
            return last
        time.sleep(0.5)
    raise AssertionError(f'Condition did not complete in {timeout}s; last={last!r}')


def remote_state(session):
    return request('GET', f'http://runner:8001/browser/medium/login/{session}')


def remote_click(session):
    url = (f'ws://skyvern:8000/v1/stream/cdp_input/browser_session/{session}'
           f'?apikey={quote(_api_key(), safe="")}&client_id={secrets.token_urlsafe(12)}')
    with connect(url, open_timeout=10) as socket:
        assert json.loads(socket.recv(timeout=120))['kind'] == 'ready'
        socket.send(json.dumps({'kind': 'take-control'}))
        for event in ('mousePressed', 'mouseReleased'):
            socket.send(json.dumps({'kind': 'mouseEvent', 'eventType': event,
                                    'button': 'left', 'x': 180, 'y': 150, 'clickCount': 1}))
        # The channel has no input acknowledgment; keep it open until the browser
        # has dispatched both events. Subsequent state assertions verify effects.
        time.sleep(0.3)


@pytest.fixture
def settings(test_outcome):
    request('DELETE', CONNECTION)
    control(action='reset')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1180, 'height': 820}, device_scale_factor=1)
        page = context.new_page()
        page.goto(BACKEND + '/screens/settings/v2.html')
        expect(page.locator('#plat-card-medium')).to_be_visible()
        expect(page.locator('body')).to_have_css('display', 'flex')
        expect(page.locator('nav').first).to_have_css('height', '48px')
        page.evaluate('document.fonts.ready')
        try:
            yield page, context
        finally:
            report = getattr(test_outcome, 'report_call', None)
            if report is not None and report.failed:
                Path('/results').mkdir(exist_ok=True)
                for index, tab in enumerate(context.pages):
                    if not tab.is_closed():
                        tab.screenshot(path=f'/results/{test_outcome.name}-tab-{index}.png')
            context.close()
            browser.close()
            request('DELETE', CONNECTION)


def begin(settings, retry_busy=False):
    page, context = settings
    card = page.locator('#plat-card-medium')
    deadline = time.monotonic() + 90
    while True:
        card.get_by_role('button', name='Connect', exact=True).click()
        with context.expect_page() as pending, page.expect_response(
            lambda response: response.url == CONNECTION and response.request.method == 'POST',
            timeout=120000,
        ) as starting:
            card.get_by_role('button', name='Browser login', exact=False).click()
        tab = pending.value
        response = starting.value
        if retry_busy and response.status == 409:
            assert response.json().get('detail', {}).get('status') == 'busy'
            assert time.monotonic() < deadline, 'Canceled verification never released its profile'
            eventually(tab.is_closed, timeout=10)
            time.sleep(0.5)
            continue
        assert response.ok, f'Browser login start returned HTTP {response.status}'
        break
    tab.wait_for_url('**/browser-session/**', timeout=120000)
    session = urlsplit(tab.url).path.split('/')[2]
    eventually(lambda: remote_state(session).get('status') == 'running')
    # Wait for the genuine Skyvern stream, not just the surrounding shell.
    expect(tab.locator('img').filter(visible=True).first).to_be_visible(timeout=120000)
    return tab, session


def login(settings, remembered=False, retry_busy=False):
    tab, session = begin(settings, retry_busy=retry_busy)
    eventually(lambda: '/login' in (remote_state(session).get('live_authentication', {}).get('url') or ''))
    remote_click(session)
    if not remembered:
        eventually(lambda: 'identity.test' in (remote_state(session).get('live_authentication', {}).get('url') or ''))
        remote_click(session)
    expect(tab.locator('[data-login-title]')).to_have_text('Medium connected', timeout=120000)
    assert not tab.is_closed()
    state = request('GET', CONNECTION)
    assert state['status'] == 'connected'
    assert state['durableConnection']['profileSaved'] is True
    tab.screenshot(path='/results/login-confirmation.png')
    return tab


def test_login_save_reopen_and_secondary_identity(settings):
    """Draw.io edge-m-1/2/3 and edge-m-disconnect: saved connection + targeted logout."""
    page, _ = settings
    tab = login(settings)
    tab.close()
    page.reload()
    expect(page.locator('#plat-card-medium').get_by_role('button', name='Disconnect')).to_be_visible()
    page.locator('#plat-card-medium').get_by_role('button', name='Disconnect').click()
    expect(page.locator('#plat-card-medium').get_by_role('button', name='Connect', exact=True)).to_be_visible(timeout=60000)
    # Google-equivalent identity remains remembered; no secondary form is used.
    tab = login(settings, remembered=True)
    tab.close()


def test_cancel_waiting(settings):
    """Cancellation must reach the backend and close the active browser."""
    page, _ = settings
    tab, session = begin(settings)
    page.locator('#plat-card-medium').get_by_role('button', name='Cancel', exact=True).click()
    expect(page.locator('#plat-card-medium').get_by_role('button', name='Connect', exact=True)).to_be_visible(timeout=60000)
    eventually(lambda: remote_state(session)['status'] in {'closed', 'completed'})
    assert request('GET', CONNECTION)['status'] == 'disconnected'


def test_expired_server_session_is_not_verified(settings):
    """Stored cookies must not be sufficient proof after remote expiry."""
    tab = login(settings)
    tab.close()
    control(action='expire', target='blog')
    # Starting the saved browser via the actual connection path must stay logged
    # out; completing that attempt must fail live persisted-profile verification.
    state = request('POST', CONNECTION)
    session = urlsplit(state['authorizationUrl']).path.split('/')[2]
    eventually(lambda: remote_state(session).get('status') == 'running')
    eventually(lambda: remote_state(session).get('live_authentication', {}).get('authenticated') is False)
    result = request('POST', CONNECTION + '/complete')
    assert result['status'] == 'failed'
    assert result['error'] == 'Medium sign-in was not completed in the browser'


def test_rejected_verification_has_visible_failure(settings):
    page, _ = settings
    control(mode='reject_verification')
    tab, session = begin(settings)
    remote_click(session)
    eventually(lambda: 'identity.test' in (remote_state(session).get('live_authentication', {}).get('url') or ''))
    remote_click(session)
    expect(tab.locator('[data-login-title]')).to_have_text('Medium verification failed', timeout=120000)
    assert request('GET', CONNECTION)['status'] == 'failed'
    assert not tab.is_closed()


def test_cancel_verification_cannot_late_connect(settings):
    """Draw.io edge-m-cancel-verifying: late completion must not undo Cancel."""
    page, _ = settings
    login(settings).close()
    page.locator('#plat-card-medium').get_by_role('button', name='Disconnect').click()
    expect(page.locator('#plat-card-medium').get_by_role('button', name='Connect', exact=True)).to_be_visible(timeout=60000)
    control(verification_delay=8)
    tab, session = begin(settings)
    remote_click(session)
    eventually(lambda: request('GET', CONNECTION)['status'] == 'verifying')
    page.locator('#plat-card-medium').get_by_role('button', name='Cancel', exact=True).click()
    expect(page.locator('#plat-card-medium').get_by_role('button', name='Connect', exact=True)).to_be_visible(timeout=60000)
    # Verify after both profile checks would have returned, not just immediately.
    time.sleep(18)
    assert request('GET', CONNECTION)['status'] == 'disconnected'
    # Explicit Cancel may close its tab; successful login must not do so.
    if not tab.is_closed():
        tab.close()
    control(verification_delay=0)
    login(settings, remembered=True, retry_busy=True).close()


def test_challenge_does_not_become_connected(settings):
    control(mode='challenge')
    page, _ = settings
    tab, session = begin(settings)
    eventually(lambda: '/challenge' in (remote_state(session).get('live_authentication', {}).get('url') or ''))
    assert request('GET', CONNECTION)['status'] == 'waiting_for_login'
    assert remote_state(session)['live_authentication']['authenticated'] is False
    page.locator('#plat-card-medium').get_by_role('button', name='Cancel', exact=True).click()
    eventually(lambda: request('GET', CONNECTION)['status'] == 'disconnected')


def test_active_profile_rejects_second_browser_logout_and_operation(settings):
    page, _ = settings
    login(settings).close()
    page.locator('#plat-card-medium').get_by_role('button', name='Disconnect').click()
    expect(page.locator('#plat-card-medium').get_by_role('button', name='Connect', exact=True)).to_be_visible(timeout=60000)
    tab, session = begin(settings)
    details = request('GET', f'http://skyvern:8000/v1/browser_sessions/{session}',
                      headers={'x-api-key': _api_key()})
    profile = details['browser_profile_id']
    organization = details['organization_id']
    assert profile
    base = 'http://runner:8001/browser/medium'
    attempts = [
        ('/login', {'profile_id': profile}),
        (f'/profiles/{profile}/logout', {'organization_id': organization}),
        ('/operations/list_articles', {'profile_id': profile, 'organization_id': organization}),
    ]
    for path, payload in attempts:
        result = request('POST', base + path, json=payload)
        assert result['status'] == 'busy', path
        assert result['success'] is False
    assert remote_state(session)['status'] == 'running'
    page.locator('#plat-card-medium').get_by_role('button', name='Cancel', exact=True).click()
    eventually(lambda: request('GET', CONNECTION)['status'] == 'disconnected')
    # A normal release is reusable; a conflict must not discard the identity.
    login(settings, remembered=True).close()
