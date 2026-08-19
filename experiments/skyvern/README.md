# Skyvern local capability experiment

This is a free, self-hosted Skyvern fixture for evaluating BlogHub's managed
browser login and persistent-profile path. It is deliberately isolated from
the main BlogHub compose stack and binds every host port to loopback.

## Pinned source

- Skyvern source commit: `3c305c911f91beee3f04308453f3d9913f610efc`
- Skyvern runtime: `1.0.50`, pinned by image digest in the compose file
- Skyvern UI and PostgreSQL are also pinned by digest
- Upstream compose source: <https://github.com/Skyvern-AI/skyvern/blob/3c305c911f91beee3f04308453f3d9913f610efc/docker-compose.yml>

## Start it

```bash
cd experiments/skyvern
cp .env.example .env
docker compose up -d --wait --wait-timeout 300
curl --fail http://127.0.0.1:8000/api/v1/heartbeat
```

Open <http://localhost:8080>. The first boot can take several minutes while
Skyvern initializes PostgreSQL and downloads its browser.

The pinned Skyvern release has a migration-check mismatch involving
`ck_google_oauth_credentials_state`. The narrowly scoped startup wrapper waits
for that constraint and removes it before Skyvern checks for schema drift.
Remove the workaround when upgrading Skyvern; do not carry it to an unpinned
release without reproducing the issue.

The 1.0.50 home and browser-list pages may also show **Unable to verify Skyvern
API key**. In this release, the generated key succeeds against browser and
workflow endpoints while two UI diagnostics endpoints still return `403`.
Treat the banner as an upstream UI issue only after the heartbeat and a real
browser session both succeed.

## Capability checklist

1. Create a browser session for `https://example.com` and verify the live
   stream renders.
2. Select **Take control** and confirm mouse and keyboard input reaches the
   remote browser.
3. Sign into a disposable test account, save the session as a browser profile,
   close it, and start a new session from the profile. Confirm the login state
   survives the new browser process.
4. Create a credential with an invented password. Confirm credential list
   responses omit the password and neither username nor password appears as
   plaintext in `/data/credential_vault` inside the Skyvern container. Delete
   the test credential.
5. Open the target publisher login and verify both the public site and the
   authentication handoff. Do not publish during this experiment.

Skyvern blocks loopback destinations submitted through its browser-session API.
Keep that SSRF protection enabled; use a harmless public fixture when testing
browser sessions.

## Results on 2026-08-18

| Capability | Result |
| --- | --- |
| API, UI, PostgreSQL health | Pass |
| Headed Chromium live stream | Pass |
| Human/Playwright live takeover | Pass |
| Login through streamed browser | Pass, using a public disposable login fixture |
| Browser-profile cookie persistence | Pass across a new Chromium process |
| Local encrypted credential vault | Pass; password redacted and test values absent from vault files |
| Hashnode public application | Pass |
| Hashnode `/login` verification | **Blocked**: Vercel Security Checkpoint reports `Failed to verify your browser`, code 19 |
| Hashnode `/login` with Patchright override | Pass; real Google, LinkedIn, GitHub, and email login options render |
| Patchright live takeover and profile restore | Pass |

The stock result means the upstream image is a useful integration substrate but
does not validate unattended Hashnode login. Skyvern's free image registers
local Playwright Chromium, while its `stealth-chromium` session type is not a
bundled free local browser engine.

The experimental override replaces Skyvern's Playwright imports with
[Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python) `1.62.1`
and keeps the Chromium already pinned in Skyvern's image. This passed the same
Hashnode checkpoint on this machine:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.patchright.yml \
  up -d --build --wait --wait-timeout 300
```

The override is intentionally experimental. Its headed launcher omits
Skyvern's HAR, video, fixed viewport, custom browser arguments, and custom
headers because that bundle closed Patchright's browser during `Page.enable`.
Live streaming, takeover, browser profiles, and profile restoration were
verified. Downloads, recording, and HAR must be tested or reintroduced one
option at a time before this image is considered a drop-in production
replacement.

No Skyvern LLM is enabled here. BlogHub owns the connection lifecycle while
Skyvern supplies isolated browser sessions, streaming, profiles, and credentials.

## Security boundaries

- Keep ports loopback-only unless authentication and TLS are added.
- Never commit `.env`, `.skyvern/`, browser profiles, vault data, or artifacts.
- Set `LOCAL_CREDENTIAL_VAULT_KEY` from an external secret manager before
  storing real credentials. The generated local key is for disposable testing.
- Prefer OAuth/session profiles over storing a GitHub account password.

Stop the experiment with:

```bash
docker compose down
```

Add `--volumes` only when intentionally deleting all experimental state.
