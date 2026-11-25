# ClipForge's TikTok token broker

Status (2026-11-25): written and tested against a stand-in TikTok (`tests/test_tiktok_broker.py`). **Not deployed
yet**: it needs a host and ClipForge's TikTok app's client secret, which only the owner has.

## Why it exists

ClipForge signs in to TikTok with **one** app registration of its own, so nobody has to create a TikTok developer app
or paste codes. TikTok's Login Kit for Desktop says the app's client secret "must live server-side only", but the
token exchange, the refresh and the revoke all need it. This broker is that server side: the desktop app sends it
everything TikTok's token endpoint needs except the secret, the broker adds the secret and passes TikTok's answer back.

It keeps nothing: no tokens, no sign-in codes, no accounts, and uvicorn runs without an access log. A sign-in code is
useless without the PKCE verifier only the person's ClipForge has, and a refresh needs the person's refresh token, so
the broker can only finish what a person already approved on TikTok's page.

Open question for TikTok's review: TikTok's overview also says the refresh token should live server-side. Here it
stays encrypted on the person's computer (as YouTube's does), and the broker only passes it through. If TikTok's
reviewers ask for server-side refresh tokens, the broker would have to keep them per person (a bigger privacy change:
the privacy page would have to say so first).

## Deploy (owner, once)

Any small HTTPS host works (Google Cloud Run, Fly.io, Render, a VM behind Caddy). Example with Cloud Run:

1. `gcloud run deploy clipforge-tiktok-broker --source deploy/tiktok_broker --region us-central1
   --allow-unauthenticated --set-secrets TIKTOK_CLIENT_SECRET=tiktok-client-secret:latest
   --set-env-vars TIKTOK_CLIENT_KEY=<ClipForge's client key>`
   (store the secret in Secret Manager first; never in git, chat or a command history you share).
2. Open `https://<the address>/health`: it says `{"ok": true}` when both settings are there.
3. In the repository's GitHub settings → Secrets and variables → Actions, add:
   `CLIPFORGE_TIKTOK_CLIENT_KEY` (the client key) and `CLIPFORGE_TIKTOK_BROKER` (the https address, no trailing
   slash). Release builds then write them into the app (`scripts/write_oauth_apps.py`), and Connect TikTok works with
   one sign-in.
4. In the TikTok developer portal, Login Kit → Desktop, register the redirect URI
   `http://127.0.0.1:8765/api/oauth/tiktok/callback` (and `http://localhost:8765/api/oauth/tiktok/callback`).

## What it accepts

- `POST /token` with `{"client_key", "grant_type": "authorization_code", "code", "code_verifier", "redirect_uri"}`;
  the redirect must be ClipForge's own `http://127.0.0.1:<port>/api/oauth/tiktok/callback`.
- `POST /token` with `{"client_key", "grant_type": "refresh_token", "refresh_token"}`.
- `POST /revoke` with `{"client_key", "token"}` (Disconnect).
- `GET /health`.

Anything else, another client key, a body over 8 KB or more than 30 requests a minute from one address is refused.
