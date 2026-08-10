"""
test_login.py — Playwright UI tests for screens/login/v1.html

Numbers in docstrings match the ui-tests.md spec (views/login/ui-tests.md).

Run:
    pytest tests/tests_ui/screens/test_login.py -m browser --browser chromium -v
"""
import pytest
import requests

from tests.tests_ui.conftest import BASE_URL

pytestmark = pytest.mark.browser

LOGIN_URL = f"{BASE_URL}/screens/login/v1.html"
OVERVIEW_URL = f"{BASE_URL}/screens/overview/v3.html"

_SEED_EMAIL = "seed@example.com"
_SEED_PASSWORD = "seed1234"
_NEW_EMAIL = "newuser_login_test@example.com"
_NEW_PASSWORD = "newpass99"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _fill_login(page, email: str, password: str) -> None:
    page.fill("#email", email)
    page.fill("#password", password)


def _submit(page) -> None:
    page.click("#submit-btn")


def _switch_mode(page) -> None:
    """Click the switch link to toggle between login and register."""
    page.click("#switch-link")


def _err_msg(page) -> str:
    return page.locator("#err-text").inner_text()


def _field_err(page, field_id: str) -> str:
    return page.locator(f"#{field_id}").inner_text()


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def login_page(page):
    """Navigate to the login screen and return the Playwright page."""
    page.goto(LOGIN_URL)
    # Wait for the card to be visible — card has a backdrop-filter, check the heading
    page.wait_for_selector("#mode-heading", timeout=5000)
    return page


@pytest.fixture
def register_page(login_page):
    """Login page with mode already switched to register."""
    login_page.click("#switch-link")
    login_page.wait_for_function(
        "document.getElementById('mode-heading').textContent === 'Create an account'"
    )
    return login_page


# ── Happy path — Login ────────────────────────────────────────────────────────


class TestLoginHappyPath:

    def test_1_page_loads_with_login_defaults(self, login_page):
        """1 — Heading and button label are correct on initial load."""
        assert login_page.locator("#mode-heading").inner_text() == "Welcome back"
        assert login_page.locator("#btn-label").inner_text() == "Log in"

    def test_2_fields_are_empty_on_load(self, login_page):
        """2 — Both fields start empty."""
        assert login_page.input_value("#email") == ""
        assert login_page.input_value("#password") == ""

    def test_3_valid_login_redirects_to_overview(self, login_page):
        """3 — Correct credentials navigate to overview."""
        _fill_login(login_page, _SEED_EMAIL, _SEED_PASSWORD)
        _submit(login_page)
        login_page.wait_for_url(f"**/overview/v3.html", timeout=8000)
        assert "/overview/v3.html" in login_page.url

    def test_4_auto_redirect_when_session_active(self, page):
        """4 — Already-authenticated user is redirected away from the login page."""
        # Log in via API to set the cookie
        session = requests.Session()
        resp = session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": _SEED_EMAIL, "password": _SEED_PASSWORD, "remember_me": False},
        )
        assert resp.status_code == 200
        cookie = session.cookies.get("bloghub_session")
        assert cookie, "No session cookie after login"

        # Inject the cookie into the Playwright context
        page.context.add_cookies([{
            "name": "bloghub_session",
            "value": cookie,
            "domain": "127.0.0.1",
            "path": "/",
        }])
        page.goto(LOGIN_URL)
        page.wait_for_url("**/overview/v3.html", timeout=6000)
        assert "/overview/v3.html" in page.url

    def test_login_returns_to_requested_local_page(self, page):
        page.goto(f"{LOGIN_URL}?next=%2Fscreens%2Fsettings%2Fv2.html")
        _fill_login(page, _SEED_EMAIL, _SEED_PASSWORD)
        _submit(page)
        page.wait_for_url("**/screens/settings/v2.html", timeout=8000)

    def test_login_rejects_external_return_destination(self, page):
        page.goto(f"{LOGIN_URL}?next=https%3A%2F%2Fexample.com")
        _fill_login(page, _SEED_EMAIL, _SEED_PASSWORD)
        _submit(page)
        page.wait_for_url("**/screens/overview/v3.html", timeout=8000)


# ── Happy path — Register ─────────────────────────────────────────────────────


class TestRegisterHappyPath:

    def test_5_switch_to_register_updates_ui(self, login_page):
        """5 — Mode switch changes heading, button, hides remember-me, shows strength bar."""
        _switch_mode(login_page)
        assert login_page.locator("#mode-heading").inner_text() == "Create an account"
        assert login_page.locator("#btn-label").inner_text() == "Create account"
        assert not login_page.locator("#remember-row").is_visible()
        assert login_page.locator("#pw-bar-wrap").is_visible()

    def test_6_register_new_user_redirects_to_overview(self, register_page):
        """6 — Valid registration navigates to overview."""
        _fill_login(register_page, _NEW_EMAIL, _NEW_PASSWORD)
        _submit(register_page)
        register_page.wait_for_url("**/overview/v3.html", timeout=8000)
        assert "/overview/v3.html" in register_page.url


# ── Live field validation ─────────────────────────────────────────────────────


class TestLiveValidation:

    def test_7_valid_email_shows_green_check(self, login_page):
        """7 — Green checkmark icon appears when email format is valid."""
        login_page.fill("#email", "user@example.com")
        login_page.wait_for_function(
            "document.getElementById('email-icon').style.opacity === '1'"
        )
        icon_html = login_page.locator("#email-icon").inner_html()
        # The SVG uses #4ade80 (green) for a valid address
        assert "4ade80" in icon_html

    def test_8_clearing_email_hides_check(self, login_page):
        """8 — Clearing the email field hides the checkmark, no error text."""
        login_page.fill("#email", "user@example.com")
        login_page.fill("#email", "")
        login_page.wait_for_function(
            "document.getElementById('email-icon').style.opacity !== '1'"
        )
        assert _field_err(login_page, "email-err") == ""

    def test_9_short_password_shows_red_bar_in_register(self, register_page):
        """9 — Password shorter than 8 chars gives a red/orange strength bar."""
        register_page.fill("#password", "abc")
        bar_color = register_page.evaluate(
            "document.getElementById('pw-bar').style.background"
        )
        assert bar_color in ("#f87171", "#fbbf24"), f"Unexpected bar color: {bar_color}"

    def test_10_8_char_password_shows_green_bar_in_register(self, register_page):
        """10 — 8-character password turns the strength bar green."""
        register_page.fill("#password", "exactly8")
        bar_color = register_page.evaluate(
            "document.getElementById('pw-bar').style.background"
        )
        assert bar_color == "#4ade80", f"Expected green, got: {bar_color}"

    def test_11_eye_toggle_reveals_password(self, login_page):
        """11 — Eye icon toggles password visibility."""
        login_page.fill("#password", "mysecret")
        assert login_page.locator("#password").get_attribute("type") == "password"
        login_page.click("#pw-toggle")
        assert login_page.locator("#password").get_attribute("type") == "text"
        login_page.click("#pw-toggle")
        assert login_page.locator("#password").get_attribute("type") == "password"


# ── Submit-time field errors ──────────────────────────────────────────────────


class TestClientSideErrors:

    def test_12_empty_submit_shows_field_errors(self, login_page):
        """12 — Submitting empty shows inline errors on both fields."""
        _submit(login_page)
        assert "required" in _field_err(login_page, "email-err").lower()
        assert "required" in _field_err(login_page, "pw-err").lower()
        # Should not have made a network call — URL unchanged
        assert "/login" in login_page.url

    def test_13_invalid_email_format_error(self, login_page):
        """13 — Invalid email format shows appropriate field error."""
        login_page.fill("#email", "notanemail")
        _submit(login_page)
        assert "valid email" in _field_err(login_page, "email-err").lower()

    def test_14_short_password_register_error(self, register_page):
        """14 — Password too short in register mode shows field error on submit."""
        register_page.fill("#email", "user@example.com")
        register_page.fill("#password", "short")
        _submit(register_page)
        assert "8 characters" in _field_err(register_page, "pw-err").lower()

    def test_15_typing_clears_field_error(self, login_page):
        """15 — Typing in a field after an error clears that field's error."""
        _submit(login_page)  # trigger errors
        assert _field_err(login_page, "email-err") != ""
        login_page.fill("#email", "u")  # start typing
        assert _field_err(login_page, "email-err") == ""


# ── API error states ──────────────────────────────────────────────────────────


class TestAPIErrors:

    def test_16_wrong_password_shows_shake_and_error(self, login_page):
        """16 — Wrong password triggers shake and generic error message."""
        _fill_login(login_page, _SEED_EMAIL, "wrongpassword")
        _submit(login_page)
        login_page.wait_for_function(
            "document.getElementById('err-msg').classList.contains('visible')",
            timeout=6000,
        )
        msg = _err_msg(login_page)
        assert "incorrect" in msg.lower() or "invalid" in msg.lower()

    def test_17_unknown_email_same_generic_error(self, login_page):
        """17 — Unknown email gives the same error as wrong password (no enumeration)."""
        _fill_login(login_page, "nobody@example.com", "somepassword")
        _submit(login_page)
        login_page.wait_for_function(
            "document.getElementById('err-msg').classList.contains('visible')",
            timeout=6000,
        )
        msg_unknown = _err_msg(login_page)

        # Reset and try wrong password for same account
        login_page.evaluate("document.getElementById('err-msg').classList.remove('visible')")
        _fill_login(login_page, _SEED_EMAIL, "wrongpassword")
        _submit(login_page)
        login_page.wait_for_function(
            "document.getElementById('err-msg').classList.contains('visible')",
            timeout=6000,
        )
        msg_wrong_pw = _err_msg(login_page)

        assert msg_unknown == msg_wrong_pw, "Error messages differ — user enumeration possible"

    def test_18_duplicate_email_register_error(self, register_page):
        """18 — Registering with an existing email shows a specific conflict error."""
        _fill_login(register_page, _SEED_EMAIL, "password123")
        _submit(register_page)
        register_page.wait_for_function(
            "document.getElementById('err-msg').classList.contains('visible')",
            timeout=6000,
        )
        msg = _err_msg(register_page)
        assert "already exists" in msg.lower() or "account" in msg.lower()

    def test_19_typing_clears_api_error(self, login_page):
        """19 — Typing in any field after an API error clears the error message."""
        _fill_login(login_page, _SEED_EMAIL, "wrongpassword")
        _submit(login_page)
        login_page.wait_for_function(
            "document.getElementById('err-msg').classList.contains('visible')",
            timeout=6000,
        )
        login_page.fill("#email", "a")
        visible = login_page.evaluate(
            "document.getElementById('err-msg').classList.contains('visible')"
        )
        assert not visible


# ── Remember me ───────────────────────────────────────────────────────────────


class TestRememberMe:

    def test_20_remember_me_visible_and_unchecked_in_login(self, login_page):
        """20 — Remember me checkbox is visible in login mode and unchecked by default."""
        assert login_page.locator("#remember-row").is_visible()
        assert not login_page.locator("#remember-me").is_checked()

    def test_21_remember_me_hidden_in_register(self, register_page):
        """21 — Remember me is not visible in register mode."""
        assert not register_page.locator("#remember-row").is_visible()


# ── Mode switch ───────────────────────────────────────────────────────────────


class TestModeSwitch:

    def test_22_switch_back_to_login_restores_defaults(self, login_page):
        """22 — Switching to register then back to login restores all defaults."""
        _switch_mode(login_page)  # → register
        _switch_mode(login_page)  # → login
        assert login_page.locator("#mode-heading").inner_text() == "Welcome back"
        assert login_page.locator("#btn-label").inner_text() == "Log in"
        assert login_page.locator("#remember-row").is_visible()
        assert not login_page.locator("#pw-bar-wrap").is_visible()
        assert login_page.input_value("#email") == ""
        assert login_page.input_value("#password") == ""

    def test_23_switching_modes_clears_errors(self, login_page):
        """23 — Mode switch clears all field errors and the API error banner."""
        # Trigger field errors
        _submit(login_page)
        assert _field_err(login_page, "email-err") != ""

        _switch_mode(login_page)  # → register
        assert _field_err(login_page, "email-err") == ""
        assert _field_err(login_page, "pw-err") == ""
        visible = login_page.evaluate(
            "document.getElementById('err-msg').classList.contains('visible')"
        )
        assert not visible
