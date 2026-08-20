# Patchright Hashnode checkpoint probe

This probe answers one question before Patchright is coupled to Skyvern: can a
current, headed Google Chrome controlled by Patchright reach Hashnode's login
screen from this machine without failing Vercel's browser verification?

It uses a persistent headed profile, no fixed viewport, and no custom user agent
or browser headers. For the minimal comparison, Patchright controls the Chromium
already pinned in Skyvern's image. The probe does not enter credentials and
cannot publish anything.

Run it with:

```bash
docker compose -f compose.yml up --build --abort-on-container-exit
cat artifacts/result.json
```

Inspect `artifacts/hashnode-login.png`. A useful result is `login_available` or
`redirected_without_checkpoint`. Do not proceed to the Skyvern integration when
the result begins with `blocked_`.

Observed result on 2026-08-18:

```json
{
  "classification": "login_available",
  "final_url": "https://hashnode.com/login",
  "title": "Log In | Hashnode",
  "browser_mode": "custom_executable"
}
```

The image pins Patchright `1.62.1` and derives from the same pinned Skyvern image
as the baseline experiment. On 2026-08-18 this combination reached Hashnode's
real login form without the Vercel code-19 failure seen with stock Playwright.
The profile is stored in a Docker named volume; the screenshot and
classification are disposable local artifacts.
