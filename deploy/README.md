# Deploying ClipForge in cloud mode (owner-only)

Status: the configuration below is **prepared and tested locally with fake providers; it has not been deployed**.
No server, provider account or domain exists yet. No paid resource is required by this configuration.

## What runs

One Linux VM (x86_64 or ARM64): Caddy (HTTPS, reverse proxy) → ClipForge on `127.0.0.1:8765` (API, page,
durable jobs, scheduler, one heavy processing slot) → SQLite and media on the VM's persistent disk. Sign-in is
Google (or any OpenID Connect provider) restricted to the configured owner subject. Nothing else is required.

## One-time setup (owner, on the server)

1. Create the user and folders:
   `sudo useradd --system --home /var/lib/clipforge clipforge && sudo mkdir -p /etc/clipforge /var/lib/clipforge /opt/clipforge && sudo chown clipforge: /var/lib/clipforge`
2. Install Python 3.12, FFmpeg and Caddy from the distribution, copy the repository to `/opt/clipforge`, then
   `python3.12 -m venv .venv && .venv/bin/pip install -r requirements-cloud.txt`.
   faster-whisper/CTranslate2 publish Linux ARM64 wheels; on a CPU server set Settings → Advanced → transcription
   device to CPU deliberately. Autopilot never falls back to the CPU silently (rule 4).
3. Key and secrets (never in chat, never in git):
   `openssl rand -base64 32 | sudo tee /etc/clipforge/secret.key >/dev/null`
   write the OIDC client secret to `/etc/clipforge/oidc-client-secret`, then
   `sudo chown clipforge: /etc/clipforge/secret.key /etc/clipforge/oidc-client-secret && sudo chmod 600 /etc/clipforge/*`.
   Keep a copy of `secret.key` somewhere safe and separate from data backups: without it, saved tokens cannot be
   decrypted (reconnect the accounts).
4. `sudo cp deploy/clipforge.env.example /etc/clipforge/clipforge.env` and fill in the host, client ID and your
   subject. Find your subject by signing in once: the private-studio page is shown and the server log records
   `refused identity issuer|subject` — copy that value into `CLIPFOUNDRY_OWNER_SUBJECTS`.
5. Google Cloud console: an OAuth **Web application** client for sign-in with the redirect URI
   `https://<host>/api/auth/callback`; for YouTube publishing add `https://<host>/api/oauth/youtube/callback`
   to the publishing client. TikTok: add `https://<host>/api/oauth/tiktok/callback`.
6. `sudo cp deploy/Caddyfile /etc/caddy/Caddyfile` (replace the host), `sudo cp deploy/clipforge.service
   /etc/systemd/system/`, then `sudo systemctl enable --now clipforge caddy`.

The app **refuses to start** in cloud mode while any protection is missing (HTTPS address, provider settings,
owner subject, private key file outside the data folder, sign-up off) and prints the list of problems.

## Checks after starting

- `curl -s https://<host>/healthz` → `{"ok": true}`; `curl -s https://<host>/api/projects` → 401.
- Sign in on a computer and on a phone; both show the same projects.

## Backup and restore

- Backup (safe while running): `sudo -u clipforge .venv/bin/python -m clipfoundry backup /var/backups/clipforge-$(date +%F)`
  — a consistent SQLite copy plus every data file and a SHA-256 manifest. Store `secret.key` separately.
- Restore: stop the service, then `sudo -u clipforge .venv/bin/python -m clipfoundry restore <backup> --into /var/lib/clipforge`
  (verifies every hash first; refuses a folder that already has a database).
- Retention preview: `.venv/bin/python -m clipfoundry retention` lists only regenerable caches and expired
  unfinished uploads. Originals and finished renders are never listed.

## Moving the desktop data to the server (cutover)

1. On the desktop: Office → Pause publishing, and wait until no upload is transferring. Note any post whose
   outcome is unknown and resolve it on its post page first.
2. Quit ClipFoundry/ClipForge on the desktop, then `python -m clipfoundry backup <folder>` there.
3. Copy the backup to the server and restore it (above). Project paths inside the database still point at the
   desktop folders: run `.venv/bin/python -m clipfoundry restore` into the configured data folder, then start the
   service; projects whose source files moved show a clear "source missing" state rather than wrong media.
4. Reconnect YouTube/TikTok on the server (Accounts → Reconnect). Windows DPAPI and Mac Keychain secrets cannot be
   decrypted on Linux; base64 secrets from a Linux desktop are re-encrypted automatically at the first start.
5. Resume publishing on the server only. Never run the desktop and the server schedulers against copies of the same
   queue. Rollback: stop the server, start the desktop with Pause publishing still on, and reconcile before resuming.

## Not verified here

Real Google/TikTok sign-in and uploads, a real VM (Oracle A1 or other), ARM64 wheels, Caddy certificates and
throughput. See `docs/clipforge/FEATURE_CHECKLIST.md` for status and `scripts/benchmark_batch.py` for the
capacity harness.
