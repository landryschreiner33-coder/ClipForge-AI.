# Check ClipFoundry from your phone

The phone dashboard shows what your PC is doing, today's posting counts and anything needing attention.
It runs beside the desktop app and is off until you enable it. Keep the PC awake and ClipFoundry open:
the phone cannot continue work or retrieve fresh status after the PC or app stops.

## Connect with Tailscale

Tailscale is the default choice for checking at home or away. It provides a private, encrypted network
between your devices. ClipFoundry does not install Tailscale, sign in for you or change its configuration.

1. Install [Tailscale](https://tailscale.com/download) on the PC and phone, and sign into the same account.
   Make sure both devices are connected in Tailscale.
2. On the PC, open **Settings → Integrations → Check from your phone**.
3. Leave **Connect through** set to **Tailscale · at home or away (recommended)**.
   Usually you can leave **PC network address (optional)** empty. If necessary, enter this PC's Tailscale
   IPv4 address, shown in Tailscale; do not enter the phone's address.
4. Choose **Turn on phone dashboard**, then open the displayed address in your phone's browser.
   **Copy phone address** copies this ordinary address; it contains no pairing code or access key.
5. On the PC, choose **Get pairing code**. Enter its eight digits on the phone and choose **Connect phone**.
   The code works once and expires after five minutes. **New pairing code** replaces the previous code.

The address usually looks like `http://100.x.x.x:8766`. The browser page uses HTTP inside Tailscale's
encrypted network. Use the exact displayed address: ClipFoundry may choose another available port if
its default phone port is occupied. The desktop app keeps its existing localhost address and port.

The phone initially keeps its access key for the current browser session. Select **Remember this phone**
before pairing only on your own phone if you want the browser to keep access after that session ends.
Browser privacy settings may prevent storage; the open page can still work until it is closed or reloaded.

You can bookmark the address or use your browser's **Add to Home Screen** shortcut where available.
This is a browser dashboard; an installable app, service worker or offline operation is not provided.

## Use trusted home Wi-Fi

Choose **Home Wi-Fi · same network only** if you only need access while both devices are on your home network.
Follow the same enable-and-pair steps. Automatic selection uses a private IPv4 address belonging to the PC;
you can enter its address yourself if necessary.

Wi-Fi mode sends the dashboard and access key through unencrypted HTTP. Use a trusted home network.
Tailscale is preferable when you need encrypted access or want to check from away. A guest network may isolate
devices even when both appear to use the same Wi-Fi.

Do not forward a router port, set up a public tunnel or expose the desktop app to make this work.
The companion accepts only an appropriate private IPv4 address that the PC can actually bind:
Tailscale's `100.64.0.0/10` range, or home-network `10.x.x.x`, `172.16`–`172.31.x.x`, and `192.168.x.x` ranges.
Public addresses, hostnames and wildcard listening addresses are rejected.

## What the dashboard shows

- **Right now:** the current activity, Running/Paused/Stopped state, publishing pause and worker availability.
  A current video's short title and processing step appear when reported by the PC. Percentages use measured
  job progress. **Progress not reported** means no measurement is available; elapsed time never fills a bar.
- **Today:** unique clips published or scheduled, separate platform-post counts, finished Autopilot/live clips
  and the configured daily clip target. One clip planned on YouTube and TikTok is one clip and two platform posts.
  These counts use the PC's configured Autopilot time zone, including daylight-saving days.
- **Next planned post:** its platform, short title, planned time and current scheduling status.
  Awaiting approval and **Upload not confirmed** remain explicit; a plan is not a promise that a post will go out.
- **Needs attention** and **Posting queue:** a short attention list and Ready/Review/Fix/Scheduled counts.
  Handle approvals, account reconnection and any other changes on the PC.
- **System check:** actual Healthy/Degraded/Error/Unknown readings and when the PC checked them.

The phone shows status summaries, not videos, thumbnails, transcripts, Brain notes, account identity,
credentials, filesystem paths or raw diagnostic messages. It cannot start or stop Autopilot, approve posts,
connect accounts, edit settings, download media or publish anything. Existing desktop publishing permissions
and checks continue to apply.

**Live** means the dashboard received a current response from the PC. If it cannot reach the PC, it changes to
**Not live**, keeps the last received values with a warning and shows their time. Those values may have changed.
Updates pause when the page is in the background and resume when you return. **Refresh** requests another reading;
it does not start work or upload anything. After a connection interruption, the page retries automatically.

## Remove access or pair again

Pairing grants last up to 90 days. At most eight devices can be paired at once. Grants survive a normal
ClipFoundry restart, but access still requires the PC, app and chosen private connection to be running.

- **Disconnect this phone** clears its browser-stored key and returns to pairing.
  It does not revoke a copy of that key or remove the server's grant.
- **Unpair all phones**, on the PC, immediately revokes all device grants and invalidates the pending pairing code.
  Other phones must pair again. Use this if a paired phone is lost, shared or no longer yours.
- **Turn off phone access**, on the PC, closes the phone listener. Turning it on again can restore access for
  previously paired phones whose grants are still valid. Use **Unpair all phones** as well to remove those grants.

Expired or revoked access returns the phone to pairing and clears its old status from the page.
Get a fresh code on the PC to reconnect. Repeated incorrect pairing attempts are limited; after **Too many attempts**,
wait a minute and make a new code on the PC.

## If the address will not open

First check that ClipFoundry is open and the PC is awake. For Tailscale, confirm both devices are connected to
the same account's private network. For Wi-Fi, confirm both are on the same trusted network rather than a guest
network. Check the **Check from your phone** panel for a startup error and use its current displayed address.

Windows may ask to allow ClipFoundry/Python through its firewall. If you choose to allow it, select your
**Private** network rather than opening access on public networks. You can review this in **Windows Security →
Firewall & network protection → Allow an app through firewall**. ClipFoundry does not change firewall rules itself.

If the PC's network address changes, turn off phone access and turn it on again, choosing its current address.
Update the phone's bookmark or Home Screen shortcut. The browser's stored grant belongs to its address and port,
so a changed address may require pairing again. Hostnames are not accepted as listener addresses; changing a
PC name does not automatically update a saved address.

An unavailable address or occupied explicitly selected port leaves phone access failed and reports that state
on the PC. Desktop clipping and publishing remain available. Turning phone access off and on retries setup.

## How access is separated

The desktop API remains on its existing localhost listener. A second FastAPI application serves only the phone
page, its script and stylesheet, pairing, and the authenticated status snapshot. It does not mount or forward
desktop routes, publishing/account endpoints, media or the full desktop frontend. Proxy headers are disabled.
The phone listener starts and stops with the desktop app without starting a second set of workers.

Only guarded localhost desktop controls can enable/disable the companion, issue pairing codes or revoke grants.
Ordinary settings saves cannot enable it. Pairing codes exist only in memory for their short lifetime;
per-peer and global limits bound guesses. Pairing creates a random 32-byte device key, while the local
`phone_devices` table stores its SHA-256 hash, creation/expiry times and an internal ID, not the usable key.

The phone sends its key in an `Authorization` header. Codes and keys are absent from URLs and cookies;
the server disables access logs and sends no-store/no-referrer and restrictive content-security headers.
The browser uses `sessionStorage` by default and `localStorage` only when **Remember this phone** is selected.
The status endpoint selects a fixed set of fields and does not mutate jobs, posts or settings.
Pairing registers a viewing grant; every application action still belongs to the desktop.

## Developer checks

Run from the repository root with the existing environment:

```bash
.venv/bin/python -m pytest -q tests/test_phone_monitor.py
.venv/bin/python -m pytest -m "not slow"
```

Use `.venv\Scripts\python.exe` on Windows. The focused Python suite uses temporary data, synthetic records,
ephemeral loopback listeners and private-address stand-ins. It checks pairing/authentication/revocation,
listener isolation and failure cleanup, status privacy and read-only behavior, measured progress and DST counts.
It does not use real phones, owner media, platform accounts or a real Tailscale network.

Build and run the phone browser contract checks:

```bash
cd frontend
npm run build
cd ../e2e
npx playwright test -c playwright.phone.config.ts
npx playwright test -c playwright.sandbox.config.ts phone-settings.spec.ts --project=chromium
```

The phone-specific browser configuration serves only the built phone shell on localhost and intercepts its
pair/status responses with controlled fixtures. Its status-refresh scenarios read those mocked responses;
the pairing scenario registers only a mocked grant. The Settings test runs in the isolated desktop sandbox
and intercepts phone setup actions. These checks cover interface behavior, not a real private-network connection.
The existing `e2e/tests` owner-data checks remain read-only.

Windows firewall behavior, native Windows execution, actual phone-browser behavior and real Tailscale account
connectivity require checks on the owner's devices; the automated suites do not establish those results.
