# Login View — UI Tests

These tests map directly to `tests/tests_ui/screens/test_login.py`.
Each numbered test corresponds to a test method with the same number in its docstring.

---

## Happy path — Login

**1** Page loads at `/screens/login/v1.html`. Heading reads "Welcome back". Submit button reads "Log in".

**2** Email field and password field are both visible and empty.

**3** Fill valid credentials (seed user: `seed@example.com` / `seed1234`), click "Log in".
  - Button text changes to "Signing you in…" during the request.
  - Progress bar appears along the bottom edge of the button.
  - On success: browser navigates to `/screens/overview/v3.html`.

**4** After successful login, loading back to `/screens/login/v1.html` auto-redirects to `/screens/overview/v3.html` (session already active).

---

## Happy path — Register

**5** Click "Create one" (switch link). Heading changes to "Create an account". Button label changes to "Create account". Remember me row disappears. Password strength bar appears.

**6** Fill a new email + password with 8+ characters. Password bar turns green. Click "Create account".
  - On success: navigates to `/screens/overview/v3.html`.

---

## Live field validation

**7** Type a valid email (`user@example.com`) in the email field. A green checkmark appears inside the field. No error text.

**8** Clear the email field (type then delete). Checkmark disappears. No error text shown (error appears only on submit).

**9** In register mode, type a password shorter than 8 characters. Strength bar is red/orange. No error text yet.

**10** In register mode, type a password of exactly 8 characters. Strength bar turns green. No error text.

**11** Click the eye icon next to the password field. Password becomes visible as plain text. Click again — returns to dots.

---

## Submit-time field errors (client-side)

**12** Click "Log in" with both fields empty. Email field gets a red border. Message "Email is required" appears below it. Password field gets a red border. Message "Password is required" appears below it. No API call made.

**13** Enter `notanemail` in email, leave password empty, submit. Email shows "Enter a valid email address". Password shows "Password is required".

**14** In register mode, enter a valid email and a 7-character password, submit. Password shows "Password must be at least 8 characters".

**15** After a field error appears, start typing in that field. The error text disappears.

---

## API error states

**16** Enter a valid email but wrong password. Click "Log in". Submit button shakes. Error message "Incorrect email or password" fades in below the button. Fields remain filled.

**17** Enter an email that does not exist. Click "Log in". Same generic error as test 16 — no hint that the email is unknown.

**18** In register mode, enter an email that already exists. Submit. Error message "An account with this email already exists" appears below the button.

**19** After an API error appears, start typing in either field. The error message disappears.

---

## Remember me

**20** "Remember me" checkbox is visible in login mode. It is unchecked by default.

**21** "Remember me" is not visible in register mode (hidden when mode switches).

---

## Mode switch

**22** Click "Create one" then "Log in instead". Heading returns to "Welcome back". Button returns to "Log in". Remember me reappears. Email and password fields are cleared.

**23** Switching modes clears any visible field errors and the API error message.
