# ClipFoundry Autopilot

Autopilot turns ClipFoundry into a persistent, local-first content opportunity engine: it discovers what is gaining
attention, checks whether each source may be used, finds the strongest moments, packages them for YouTube Shorts and
TikTok, schedules them, publishes the posts you approved through the official APIs, and learns from the real results.

Everything runs on your computer. The platform APIs are used only for discovery signals, publishing and reading your
own results.

## What the platforms allow (and what that means for Autopilot)

These rules come from the platforms, and they win over the 15-clips-a-day target and over full automation.

| Rule | Source | Effect in ClipFoundry |
| --- | --- | --- |
| Users must have final control over data published to YouTube; the app may only *suggest* titles, descriptions and privacy. | YouTube API Services Developer Policies | Every YouTube post waits for your approval in the Publish Center. After you approve it, it is published at its scheduled time without further clicks. |
| TikTok apps may only upload after the user expressly consents, must show a preview, must let the user edit the text, must read the creator's options before posting and must not pre-select a privacy level. | TikTok Content Sharing Guidelines | Every TikTok post waits for your approval, made on a screen that shows the preview, the creator nickname and TikTok's options (privacy is never pre-selected). |
| API data must not be used to create derived data or metrics without Google's approval. | YouTube Developer Policies III.E.4; Additional policies for derived metrics | Momentum scores (view velocity, engagement rates) are computed from YouTube data only when you confirm that your Google Cloud project was granted this. Otherwise YouTube results are ranked by YouTube's own order and shown as YouTube reported them. |
| Stored YouTube API data must be refreshed or deleted within 30 days. | YouTube Developer Policies | A maintenance job refreshes or deletes YouTube data older than 30 days. |
| Content may only be downloaded from YouTube through means YouTube authorizes, or with permission from YouTube and the rights holders. | YouTube Terms of Service | Autopilot ingests your own files (watch folders), stream URLs and direct media links you are allowed to use. Downloading platform-hosted videos with the URL importer is off by default and never happens for a source without a passing rights status. |
| `chart=mostPopular` now covers the Trending Music, Movies and Gaming charts only. | YouTube Data API revision history (July 2025) | Broad discovery uses topic searches (their own 100-call daily quota bucket since June 2026) plus channels you follow. |
| Google Trends API is an application-gated alpha; TikTok has no trend API for general developers. | Google Search Central; TikTok for Developers | Not used. Shown as unavailable in the UI. ClipFoundry never scrapes either. |
| Unaudited API projects/apps can only publish privately. | YouTube API audit; TikTok Content Posting API | Shown before scheduling and after each upload. Autopilot never claims a post is public when the platform made it private. |

## How the existing code is reused

| Requirement | Built on |
| --- | --- |
| Persistent state | `clipfoundry/db.py` (SQLite, WAL, migrations with `CREATE TABLE IF NOT EXISTS` + `ADDED_COLUMNS`) |
| Workers | New durable queue `autopilot/queue.py` on SQLite; the existing single render worker (`jobs.py`) keeps handling manual projects and now resumes after a restart |
| GPU | `pipeline/cuda.py` detection + a new `gpu.py` manager that serializes heavy GPU work across processes; `pipeline/transcribe.py` is not modified |
| Clip Hunter / Deep Analyzer | `pipeline/candidates.py` (windows), `pipeline/virality.py` (11 factors, unchanged weights), `pipeline/scoring.py` (staged evaluation), new `pipeline/deep.py` and `pipeline/diversity.py` |
| Packaging | `pipeline/postpack.py` (grounding checks) extended by `autopilot/packaging.py` |
| Publisher | `publish/youtube.py`, `publish/tiktok.py`, `publish/jobs.py` runners, reused by the autopilot publisher |
| Learning | `learning.py` and `publish/stats.py` (real metrics only) |

## Phases

1. Plan (this document).
2. Persistent tables.
3. Worker framework, restart recovery, GPU resource manager.
4. Trend Scout, Source Scout, trend scoring, rights gate, YouTube quota manager.
5. Clip Hunter, staged analysis, boundary optimization, diversity selection.
6. Packaging and grounding validation.
7. Scheduler, publication queue, dynamic replacement.
8. Live Monitor.
9. Publisher integration and Autopilot controls.
10. Learning worker.
11. Autopilot dashboard, Publish Center, legal pages, documentation.
12. End-to-end validation.
