"""Two phases run around real backend, runner and Skyvern container restarts."""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

from validation.test_login import BACKEND, CONNECTION, request, control, login


def test_prepare_restart():
    request('DELETE', CONNECTION)
    control(action='reset')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1180, 'height': 820})
        page = context.new_page()
        page.goto(BACKEND + '/screens/settings/v2.html')
        tab = login((page, context))
        tab.close()
        state = request('GET', CONNECTION)
        Path('/results/restart.json').write_text(json.dumps({
            'verifiedAt': state['verifiedAt'], 'status': state['status'],
        }))
        browser.close()


def test_after_restart():
    before = json.loads(Path('/results/restart.json').read_text())
    state = request('GET', CONNECTION)
    assert state['status'] == before['status'] == 'connected'
    assert state['verifiedAt'] == before['verifiedAt']
    assert state['durableConnection']['profileSaved'] is True
    connections = request('GET', BACKEND + '/api/connections')['connections']
    medium = next(item for item in connections if item['id'] == 'medium')
    assert medium['apiConnected'] is False
    # A persisted status alone is not proof. This launches the real persisted
    # profile headlessly and requires the fixture's authenticated article list.
    result = request('POST', BACKEND + '/api/connections/medium/sync')
    assert result['status'] == 'succeeded'
    assert result['sourceErrors'] == []
    assert result['fetched'] == 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BACKEND + '/screens/settings/v2.html')
        expect(page.locator('#plat-card-medium').get_by_role('button', name='Disconnect')).to_be_visible()
        expect(page.locator('#plat-card-medium')).to_contain_text('Browser login')
        expect(page.locator('#plat-card-medium')).not_to_contain_text('Token + browser login')
        page.screenshot(path='/results/connected-after-restart.png')
        browser.close()
    request('DELETE', CONNECTION)
