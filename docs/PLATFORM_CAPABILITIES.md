# Platform capabilities

What YouTube and TikTok allow for a single-user, local ClipFoundry, and what the code does about it. Account
connection, granted scopes, app/project approval (audit) and whether the product's use case is acceptable to the
platform are **separate** checks: passing one says nothing about the others.

## Provenance of this page

| Source | Date | Note |
| --- | --- | --- |
| Official pages listed below | **not re-read in this session** (2026-09-28) | The cloud session's network policy denied `developers.google.com` and `developers.tiktok.com`. Nothing below was re-verified here. |
| TikTok developer pages (the TikTok rows below) | re-read 2026-10-01 | Reachable from the cloud session that day; the quotes in the TikTok table are from these pages. The YouTube pages were not re-read. |
| Task specification "Audit, Finish, and Verify" | states it was checked on 2026-09-28 | Source of the TikTok Direct Post eligibility concern and of the three YouTube quota allowances. Recorded as the author's reading, not as this session's. |
| `docs/AUTOPILOT.md` and the code (`publish/`, `autopilot/quota.py`) | written in earlier phases | What the app currently assumes and enforces. |

Before relying on any row, open the URL, compare, and update the "Last verified" column with the date and what you
saw.

## Official references

| Topic | URL | Last verified |
| --- | --- | --- |
| TikTok Content Sharing Guidelines | https://developers.tiktok.com/doc/content-sharing-guidelines | 2026-10-01 |
| TikTok Content Posting API: get started | https://developers.tiktok.com/doc/content-posting-api-get-started | 2026-10-01 |
| TikTok app review guidelines | https://developers.tiktok.com/doc/app-review-guidelines | 2026-10-01 |
| TikTok: register an app (fields, URL verification) | https://developers.tiktok.com/docs/en/getting-started-create-an-app | 2026-10-01 |
| TikTok sandbox | https://developers.tiktok.com/docs/en/add-a-sandbox | 2026-10-01 |
| TikTok Login Kit for desktop (redirect URIs) | https://developers.tiktok.com/doc/login-kit-desktop | 2026-10-01 |
| YouTube Data API: getting started (quota) | https://developers.google.com/youtube/v3/getting-started | not in this session |
| YouTube quota and compliance audits | https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits | not in this session |
| YouTube API Services Developer Policies | https://developers.google.com/youtube/terms/developer-policies | not in this session |

## TikTok

| Capability | Constraint as recorded | Source | What ClipFoundry does | Status |
| --- | --- | --- | --- | --- |
| Direct Post to the profile (`video.publish`) for this app | The Content Sharing Guidelines list "A utility tool to help upload contents to the account(s) you or your team manages" and "An app that copies arbitrary contents from other platforms to TikTok" as unacceptable. The app review guidelines reject apps "for private or personal use". A single-user local tool is squarely in the first category; an audit is not a guaranteed way around it. | Content Sharing Guidelines and app review guidelines (re-read 2026-10-01) | Direct Post code exists and is contract-tested against a fake API. It is used only when the user's own app has the scope; the audit/eligibility decision is TikTok's. The product is **not** turned into a public SaaS to pursue approval. | externally-blocked (eligibility); implemented for eligible apps |
| Unaudited Direct Post | "Unaudited API Clients can only post contents in `SELF_ONLY` viewership", the posting account must be private, and at most 5 users may post in 24 hours | Content Sharing Guidelines (re-read 2026-10-01) | Explains it before posting; refusal codes map to "Needs you". Used for *Only me (staging)* | implemented, contract-tested |
| Followers / Friends audience | `privacy_level_options` from creator info lists `FOLLOWER_OF_CREATOR` / `MUTUAL_FOLLOW_FRIENDS` when allowed; with a private account only approved followers see *Followers* posts | Creator info reference and TikTok privacy help (from the owner's brief; not re-read in this session) | *Selected audience*: direct only for audited apps when the option is offered right now; otherwise a manual posting package. *Everyone* (`PUBLIC_TO_EVERYONE`) is always refused | implemented, contract-tested; audit is the user's/TikTok's |
| Upload to inbox as a draft (`video.upload`) | Works without the audit; the user finishes the post in the TikTok app | `publish/tiktok.py` | Fallback path; the post can then be linked by URL in the Publish Center | implemented, contract-tested |
| Export and manual upload in TikTok Studio | Always possible | — | Export ZIP / MP4 | verified (local) |
| Required UX before posting | Read creator info first; show the creator's nickname; privacy chosen by the user with no default; interactions (comment, duet, stitch) off unless enabled and greyed out when the account disables them; commercial content disclosure; Music Usage Confirmation; preview and editable text; explicit consent | `publish/tiktok.py`, `components/approve.tsx` | Implemented in the approval dialog; approval bound to the exact content | contract-tested (fake API); real-account check pending |
| Trends / discovery API | No trend or search API for general developers (Research API is for approved academic research) | `docs/AUTOPILOT.md` | Shown as unavailable; never scraped | not-supported |
| Retention metrics | Not available through the API used | `docs/AUTOPILOT.md` | Shown as unavailable | not-supported |
| Sandbox | Up to 10 of your own TikTok accounts as target users, no app review; "Sandbox mode does not offer access to Content Posting API for public videos" | sandbox page (re-read 2026-10-01) | Nothing special: a sandbox client key and secret are pasted like any other | untested with a real sandbox |
| App registration | Icon 1024×1024 (JPEG/PNG, up to 5 MB), name, category, description; Terms of Service and Privacy Policy URLs that must be verified (apps created after 2024-09-09), by domain or by URL prefix with a signature file uploaded to that URL; the policies must be on the official website, not hidden behind a menu | register-an-app and app review pages (re-read 2026-10-01) | The website and policies are in `docs/legal/`; publishing them is the owner's decision | owner action |
| Desktop redirect URI | Only `localhost` or `127.0.0.1`, with a port, HTTP or HTTPS, no query or fragment | Login Kit for desktop (re-read 2026-10-01) | `http://127.0.0.1:<port>/api/oauth/tiktok/callback`, shown in Settings | implemented, contract-tested |

## YouTube

| Capability | Constraint as recorded | Source | What ClipFoundry does | Status |
| --- | --- | --- | --- | --- |
| Quota | Per Cloud project per day, reset at midnight Pacific. Separate allowances for `search.list` calls, `videos.insert` calls, and units for all other methods. | Task specification (2026-09-28) and `autopilot/quota.py` (`BUCKETS`, `COSTS`) | Settings `youtube_quota_default` (10000 units), `youtube_quota_uploads` (100 calls), `youtube_quota_search` (100 calls) are **configuration**, to be set to the project's real allowances. The app counts its own calls (app-observed), believes `quotaExceeded` over its count, keeps a publishing reserve, caches discovery. Project-level usage is not readable through the API: the Google Cloud console is the authority. | implemented, unit-tested; configured limits unverified against the user's project |
| Unaudited projects | Uploads are locked to Private until the project passes the audit | `docs/AUTOPILOT.md`, `publish/jobs.py` (`locked_private`) | Reported before and after upload; never claims public | contract-tested |
| User control over published data | The app may suggest, the user decides (title, description, privacy) | Developer Policies (as recorded in `docs/AUTOPILOT.md`) | Every Autopilot post needs approval in the Publish Center; approval bound to content | unit-tested |
| Made-for-kids | Must be answered | YouTube API / COPPA | Required in approval (`scheduler.check_platform`) | unit-tested |
| Native scheduling | Upload as private with `publishAt` (YouTube then makes it public) | YouTube Data API | **Not used** (2026-10-07): `publishAt` would make a post public, so it is refused (`audience.py`, `youtube.video_body`). Posts upload at their planned time as private | unit-tested (refusal) |
| Private sharing with invited viewers | Private videos can be shared with specific Google accounts (up to 50) in YouTube Studio; no Data API call exists for it | YouTube help "private sharing" (from the owner's brief; not re-read in this session) | *Selected audience*: private upload, then "Awaiting viewer invitations" until you confirm you invited them | implemented, contract-tested; real-account check pending |
| Visibility read-back | `status.privacyStatus` on `videos.list` | YouTube Data API | Refresh compares it with the intended private visibility; public/unlisted halts YouTube uploads (drift) | contract-tested |
| Derived metrics from API data | Not without Google's approval | Developer Policies III.E.4 (as recorded) | Momentum/learning from YouTube data only with the explicit setting | unit-tested |
| Stored API data | Refresh or delete within 30 days (Authorized Data of the user's own channel may be kept by approved projects) | Developer Policies (as recorded) | Maintenance step deletes older YouTube data | unit-tested |
| Downloading platform videos | Only through means YouTube authorizes, or with permission | YouTube Terms (as recorded) | Off by default; own files preferred | unit-tested |
| `chart=mostPopular` | Covers Music, Movies, Gaming charts only (since July 2025) | Revision history (as recorded) | Topic searches within the search allowance | unit-tested |

## What still needs a real account

| Check | Why it cannot be done here | Evidence to collect |
| --- | --- | --- |
| YouTube OAuth, upload (private), `publishAt`, status read-back | needs the user's Google Cloud client and channel | video ID, privacy reported by YouTube, scheduled time |
| TikTok Login Kit, creator info, inbox draft | needs the user's TikTok developer app | creator nickname and privacy options read from TikTok, draft visible in the app |
| TikTok Direct Post | depends on TikTok accepting the app and use case | TikTok's decision; until then inbox or manual upload |
