# TikTok app setup and form draft

Open **Settings → Accounts → TikTok → Help me fill out the TikTok app form**. The same helper is available in
first-time account setup. It supplies copyable app details, a real callback address for the current local port,
two branded 1024 × 1024 PNG icons, product/scope explanations and a demo-recording checklist.

Start with **Send to my TikTok inbox** for the smallest posting scope. Direct Post and the optional statistics
scope need their own demonstrated uses. **Use these permissions in ClipFoundry**, save Settings, then reconnect:
changing a form draft does not change an existing account's granted permissions. Existing installations retain
their earlier Direct Post plus inbox choices unless the owner changes them.

The helper prepares a draft; it does not register an app, submit a review, deploy a website, sign in, verify a
domain or approve a post. Its checklist records what you report in this app tab, not platform evidence.
App review and Content Posting audit decisions must be checked in TikTok's developer portal.

## What to enter in TikTok's portal

1. Create the app with the name **ClipFoundry**, the closest video/video-editing category and platform **Desktop**.
   Use one supplied PNG icon and the helper's truthful description of a local, personal desktop editor.
2. Add **Login Kit** and **Content Posting API**. Add only the permissions used by your selected mode:
   inbox uses `user.info.basic,video.upload`; Direct Post only uses `user.info.basic,video.publish`.
   Request both posting scopes only if using both features. Statistics adds **Display API** and `video.list`.
3. In **Login Kit Desktop**, register the exact redirect shown by the app, such as
   `http://127.0.0.1:8999/api/oauth/tiktok/callback`. Use your actual port. TikTok's Desktop Login Kit permits HTTP
   on `localhost`/`127.0.0.1` with a port, unlike a public website field. ClipFoundry uses TikTok's hex-SHA256 PKCE
   challenge, an expiring random login state and an exact callback.
4. Create a **Sandbox**, add your own TikTok account as a target user and apply the changes. Paste that environment's
   client key and secret into ClipFoundry, save them and press **Connect TikTok**. Your password is entered only on
   TikTok's own page. Keep the client secret out of recordings and form documents.
5. For review, TikTok requires a real developed public website, with active Terms and Privacy links visibly on it.
   Apps created after September 9, 2024 must verify their website, Terms and Privacy URLs in TikTok's portal.
   Use your actual published HTTPS URLs. The helper checks their format without fetching them and cannot certify
   availability or ownership. Local `/legal/` previews, placeholder domains and repository source files are not a
   published website. Review the provided draft product/legal pages before deciding to publish them.
6. Record the current sandbox integration with your own content and target user. Show sign-in, the returned account,
   the exact clip preview, choices and the actual upload result. Demonstrate every requested product and scope;
   statistics requests also need the real returned metrics. TikTok permits one to five demo videos of up to 50 MB
   each. A fake-platform test or controlled UI preview is not a real integration demo.

**Download TikTok form pack** saves a ZIP containing form text/JSON, the icons and draft website/legal pages.
Entered invalid website addresses block download, including links containing credentials, query parameters or
fragments. Correct them or leave them blank to export an incomplete draft with placeholders.
It excludes settings dumps, app credentials, tokens, account identities and owner media. Website fields and
checklist choices stay in memory in this app tab until reload/close, and in the downloaded draft; they are not
stored in browser storage, the app database or as an app review decision. Saving Settings keeps the open tab's draft.
Only applying permission choices and saving Settings changes local connection preferences. Exporting the pack
never contacts TikTok or publishes the included pages.

## Limits that the form cannot remove

TikTok's current production app-review and Content Sharing guidelines reject apps for personal/private use,
internal upload utilities and arbitrary cross-platform reposting. ClipFoundry is currently a single-user desktop
tool, so form completeness does not make this use case eligible. Describe it honestly; do not represent it as
a public service or claim an audit/review result that has not happened.

Sandbox is for target-user testing and does not offer Public content posting. Unaudited Direct Post requires a
private account and `SELF_ONLY`, with at most five posting users in a 24-hour period. A private TikTok account
cannot offer Everyone. Every TikTok upload retains its per-post preview, supported privacy selection and consent.
Inbox uploads still need TikTok app approval and `video.upload`; without eligible API access, export the prepared
video/caption and post it yourself in TikTok. This helper changes none of these restrictions.

## Primary references

Checked October 11, 2026 (America/Chicago); these pages list August 4, 2026 as their last update.

* [Register your app](https://developers.tiktok.com/docs/en/getting-started-create-an-app): form fields, icon
  requirements, Desktop website and URL-ownership verification.
* [Login Kit Desktop](https://developers.tiktok.com/doc/login-kit-desktop/): loopback redirects and PKCE.
* [Add a Sandbox](https://developers.tiktok.com/docs/en/add-a-sandbox): target users and no Public posting.
* [App Review Guidelines](https://developers.tiktok.com/doc/app-review-guidelines/): public website, personal-use
  restriction, least permissions and sandbox demo requirements.
* [Content Sharing Guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines/): Direct Post
  eligibility, unaudited limits and per-post user controls.
