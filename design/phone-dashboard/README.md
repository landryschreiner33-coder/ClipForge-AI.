# Phone dashboard previews

Captured from the final built `frontend/dist/phone` with the controlled Playwright phone suite, at 390×844.
The dashboard capture is full-page. Pairing codes, grants, titles, counts, status and times are synthetic fixtures;
no owner data, real account or private-network connection is shown. These images demonstrate layout, not an
actual PC's current work, Windows behavior or real-phone execution.

* [Dashboard](dashboard-controlled.png)
* [Pairing](pairing-controlled.png)

The isolated browser suite serves the static shell on loopback, intercepts API calls and checks authorization
headers, escaping, mobile overflow, pairing/revocation/expiry, storage and stale/background/reconnect behavior.
Backend tests separately use disposable profiles and real loopback listeners.

Run `npx playwright test -c playwright.phone.config.ts` from `e2e` after building `frontend`.
Set `CLIPFOUNDRY_PHONE_PREVIEW_DIR` to a scratch directory to capture both views from controlled fixtures.
See [setup and architecture](../../docs/PHONE_DASHBOARD.md) and
[recorded verification](../../docs/IMPLEMENTATION_STATUS.md).
