# ClipFoundry → ClipForge rename plan

The owner authorized the visible product rename. This is a label change, not a data migration.

## Changes (visible)

- Shell, sign-in page, browser titles (`… · ClipForge`), navigation, onboarding, dialogs, toasts, help text,
  OAuth callback pages, export ZIP labels and generated README text inside exports.
- `config.APP_NAME = "ClipForge"` is the single source for backend messages that name the product.
- The download website copy is prepared in `docs/clipforge/WEBSITE_COPY.md` for review. The live site, old
  releases and their checksums are not modified by this build.

## Deliberately unchanged (internal compatibility names)

| Name | Why it stays |
| --- | --- |
| Python package `clipfoundry`, CLI `python -m clipfoundry` | Imports, tests, installers and the Mac bundle launch it. |
| `CLIPFOUNDRY_*` environment variables | Existing launchers, CI and owner scripts set them. New cloud variables use the same prefix for consistency. |
| Data folder and `clipfoundry.db` | Renaming would open an empty profile. The rename must keep every project, note, account and approval. |
| `x-clipfoundry` request header | Existing publish guard; the frontend sends it on every mutation. |
| Windows DPAPI entropy, macOS Keychain service and bundle IDs | Changing them would make saved tokens undecryptable. |
| OAuth client IDs, redirect paths `/api/oauth/{platform}/callback` | Registered in Google/TikTok consoles. |
| `.clipfoundry/ai-change-log.jsonl`, historical docs and links | History; not product UI. |

## Provider-console checklist (owner action, not done by this build)

- Google Cloud OAuth consent screen: app name ClipForge, the same robot icon, privacy/terms links.
- TikTok developer portal: app name/icon update (may require re-review).
- For cloud mode: add the HTTPS callback `https://<your host>/api/oauth/youtube/callback` and
  `/api/oauth/tiktok/callback`, and a separate Google OIDC web client for sign-in with callback
  `https://<your host>/api/auth/callback`.

## Verification

`tests/test_clipforge_rename.py` opens a profile created with the old ClipFoundry data and checks that the same
projects, Brain notes, accounts, publications and approvals are present under the ClipForge label, that no new
data folder is created, and that old routes and settings keys still work.
