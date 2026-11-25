# ClipFoundry Autopilot

Autopilot makes clips from a recorded video you submit, or from live streams while they are live (**Missions →
Live streams**, several at once). In **Missions**, paste a supported public video link or
choose a file, then choose **Make & upload clips** or **Make clips only**. Relevant supported Brain notes and
example preferences guide selection and editing; Settings fill missing choices. Processing stays on this PC.
No search API key is needed for this workflow.

New posting plans use a **30-minute minimum gap** by default. The old zero-gap default is corrected once on
upgrade; positive custom gaps and later choices stay intact. Settings → Advanced → Autopilot posting changes
the gap (0 disables it), without adding a daily cap. Automatic pending collisions are replanned, and already
queued uploads also respect per-account pacing after a restart or platform wait. Your explicit rescheduled times,
approval content and active/uncertain upload identities are preserved.

Brain labels such as TikTok and Shorts apply across topics; actual topic tags still narrow the lesson. The
clip editor shows which saved revisions influenced selection or rendering. Auto framing follows measured moving
content if faces are missed/lost; explicit Center/Manual choices stay fixed. Existing output files need a new
render to use that change. A valid existing Make & upload request also supplies its source reuse statement in
Queue, rather than asking you to type it for each resulting clip. It does not authorize old backlog or new inputs.

> **Names:** Home is **Office**, Autopilot is **Missions**, Library is **Clips**, Posts is **Queue**, and **Brain**
> has its own workspace. Old addresses still work. See [OFFICE.md](OFFICE.md).

**Submitted videos is the default input mode.** Periodic searches, folder admission and stale queued discovery
handlers do not find new work in this mode. Existing media, saved search connections, old sources and post history
remain intact. Optional **Discover videos** mode is under Settings → Advanced → Autopilot details → Video input.
The discovery, watched-folder and live-monitor *discovery* descriptions later in this document apply only to that
optional mode. Live streams you add yourself are covered under *Clip live streams* below.

For **Make & upload clips**, the form lists every connected YouTube channel and the confirmed audience. Tick the
channels this input's clips go to: one, a few, or **All** (the channels marked *Tick for new posts* in Accounts start
ticked). Each passing clip uploads once to each ticked channel; every channel keeps its own posting pace, and a
channel that needs Reconnect holds only its own posts. All is saved as the channels connected at that moment, so a
channel you connect later is never included. Choose a
genuine made-for-kids answer and the reuse basis for this video's footage and sound, then confirm the input once.
Qualifying new clips from that input can upload without another click on every clip. The stored request is bound
to that source, acquired original hash, project, the ticked channels, audience, kids answer and current
terms/credit. A request saved before channels could be chosen names the default channel only and behaves as before. Every
post still needs grounded metadata, a passing exact-file quality report and a fresh hash before upload. An
assertion does not verify ownership or grant rights you do not have. Merely pasting a link grants no permission.
Permission answers are stored with the submission/posts, never in Brain.

This request applies only to its input's newly generated YouTube clips. It does not approve old backlog, later
inputs or TikTok posts, and does not change global audience or standing permission. It can schedule and dispatch
its clips even if broad automatic scheduling, automatic publishing or the general YouTube platform toggle is off.
**Pause publishing**, **Stop all jobs**, canceled/blocked inputs, changed original/destination/terms, quality holds,
platform quotas and exact server waits still apply. A missing or replaced original holds new uploads; uncertain
transfers retain their identity and reconcile rather than uploading again blindly. **Cancel video** stops future
work without deleting completed clips or posts already on YouTube. Existing files and published videos are not
rewritten by the update.

**Cancel upload** (on a post that is uploading now: the post page and the Posts menu; added 2026-11-25) is different
from canceling its job in Advanced → Jobs (which only postpones the post to a new time) and from Stop all. The upload
stops after the part being sent and the post ends as *canceled*: nothing is posted, the clip and its file stay, and
**Retry** makes exactly one new upload (a new session; the canceled one never gets its last part, so YouTube makes no
video from it). The request is written into the upload record (`info.cancel_requested_at`) and the post's history, so
a waiting or retrying job, a restart or the orphan check never revives the canceled upload. When the platform already
has the whole video, ClipForge shows that instead: YouTube's upload session is asked (`youtube.session_state`); a
finished video is recorded as posted ("Too late to cancel"), and anything unclear after the last part keeps the
outcome-unknown hold (rule 6). A TikTok upload whose chunks all arrived is processing on TikTok and can't be stopped
from ClipForge; the page says so. Publish Center's own **Cancel upload** follows the same rules.

**Make clips only** requires no upload consent and creates no automatic posting plan. Use Clips to edit/export the
results. Existing Queue backlog keeps the default manual review behavior. Inline previews and **Approve selected**
can approve up to 50 selected YouTube posts with one explicit batch review; this is not permission for future work.
TikTok always requires its supported per-post choices and consent or a manual posting handoff.

There is no app daily source/upload cap by default: **0 means unlimited**. Positive owner caps, quality floors,
bounded queues, disk/GPU availability and platform/API limits remain active. Up to five strong clips per source is
a quality-oriented default, not a daily quota. No clip or upload is promised for unusable or weak input.

Contents: [platform rules](#what-the-platforms-allow-and-what-that-means-for-autopilot) ·
[setup](#setting-it-up) · [how it works](#how-it-works) · [scores](#scores) · [Posts](#posts) ·
[controls and emergency stop](#controls-and-emergency-stop) · [what is not possible](#blocked-or-limited-capabilities) ·
[unattended operation](UNATTENDED.md) ·
[legal pages](#legal-pages-terms-of-service-and-privacy-policy) · [troubleshooting](#troubleshooting)

## What the platforms allow (and what that means for Autopilot)

These rules come from the platforms and apply to continuous operation too.

| Rule | Source | Effect in ClipFoundry |
| --- | --- | --- |
| Users must control what is published to YouTube and know what the app does in their name. | YouTube API Services Developer Policies | **Make & upload clips** explicitly authorizes qualifying new clips from one submitted input to the displayed account/audience. Each is labeled as approved for its submitted video, not individually reviewed. Old backlog stays in *Needs review*. Optional standing consent applies only outside review mode. Unstarted work stays cancellable. |
| TikTok apps may only upload after the user expressly consents, must show a preview, must let the user edit the text, must read the creator's options before posting and must not pre-select a privacy level. | TikTok Content Sharing Guidelines | Every TikTok post waits for your approval, made on the post's own page, which shows the preview, the creator nickname and TikTok's options (privacy is never pre-selected). Automatic publishing is not offered for TikTok, and the app says why. Once approved, a post goes out at its time by itself. |
| API data must not be used to create derived data or metrics without Google's approval. | YouTube Developer Policies III.E.4; Additional policies for derived metrics | Momentum scores (view velocity, engagement rates) are computed from YouTube data only when you confirm that your Google Cloud project was granted this. Otherwise YouTube results are ranked by YouTube's own order and shown as YouTube reported them. |
| Stored YouTube API data must be refreshed or deleted within 30 days. Approved projects may keep statistics of the user's own videos (Authorized Data) longer. | YouTube Developer Policies; Additional policies for derived metrics and data storage | A maintenance job deletes YouTube data older than 30 days. With the approval setting on and the channel connected, only the statistics of your own videos are kept longer. |
| Content may only be downloaded from YouTube through means YouTube authorizes, or with permission from YouTube and the rights holders. | YouTube Terms of Service | Getting the file is decided separately from the right to reuse it (`autopilot/access.py`). Autopilot uses your own files, a folder or file links a creator shares with you under an agreement, a free-license library's own downloads, and direct links you configured. A connected account or public availability never proves download permission. An explicitly submitted link uses guarded public extraction without a search key; the owner remains responsible for its lawful use. Other inputs keep the existing download settings. |
| `chart=mostPopular` now covers the Trending Music, Movies and Gaming charts only. | YouTube Data API revision history (July 2025) | Broad discovery uses topic searches (their own 100-call daily quota bucket since June 2026) plus channels you follow. |
| Google Trends API is an application-gated alpha; TikTok has no trend API for general developers. | Google Search Central; TikTok for Developers | Not used. Shown as unavailable in the UI. ClipFoundry never scrapes either. |
| YouTube project status | Current API docs | Unverified projects may upload Public; audits cover more quota. |
| Unaudited TikTok apps | Content Posting API | Direct Post stays restricted; approval and per-post consent matter. |

YouTube's [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert) and
[videos](https://developers.google.com/youtube/v3/docs/videos) documentation, updated October 8, 2026 and checked
October 10, now permit Public uploads from unverified projects. API audits apply to quota increases. ClipFoundry
still requires explicit Public setup and appropriate account-bound approval/permission, then reports actual returned
visibility. TikTok's app audit remains separate; a private TikTok account cannot offer Everyone.

## Setting it up

### Submit a recorded video

1. Connect your intended YouTube channel in Settings → Integrations and confirm **Who watches**. Public and Private
   remain deliberate choices; existing posts keep their audience. Private sharing still happens in YouTube Studio.
2. Open **Missions → Add a video**. Paste a public recorded-video link or select/drop a supported file (default
   source cap 8 GB; configured duration and disk limits also apply). Login-only, protected and unavailable
   sources are not accepted. A live link pasted here is recorded like one added in **Live streams** (below). Link import contacts the supplied service using the
   guarded importer, without search-service keys, cookies or authentication bypass.
3. Choose **Make & upload clips**. Tick the YouTube channels, review the audience, answer made-for-kids, choose your reuse basis
   and tick the confirmation. **Another legal basis** needs your explanation; the other bases offer optional
   details. Press **Make & upload clips** once. Or choose **Make clips only** to keep results local.
4. Keep the app open and PC awake. **Submitted videos** reports actual ready/waiting/uploading/uploaded counts and
   holds. **View clips** opens results; **Cancel video** cancels future processing/uploads. Resume an existing
   emergency Stop explicitly before adding work; submitting a video does not clear Stop or publishing pause.

The accepted input and its request are stored together. A restart can recover an accepted input whose first job
was not yet queued, without reviving deliberately canceled work. Re-pasting an existing video does not grant its
old project/backlog a new upload request. The original uploaded file is copied under the data folder's
`submitted/<id>/`; your own original is not changed. Saved requests and post history remain for audit/recovery.

### Clip live streams (several at once)

**Missions → Live streams** (`#/missions/live`; also **Make → Clip a live stream**). Paste one or more stream links,
one per line (at most 10 at a time): a Twitch or Kick channel (`twitch.tv/name`, `kick.com/name`), a YouTube live
video or a channel's live page (`youtube.com/@name/live`), or a public `https://…m3u8` stream. RTMP, SRT and RTSP
addresses are refused. Each link becomes its own input with its own **Make & upload clips** request (the same
account, audience, made-for-kids answer and reuse basis as a video). The saved request says that the link is
recorded while it is live and that qualifying clips upload during the stream and from the full recording afterwards.
It covers that one broadcast only, never the channel's later streams.

- **Waiting for the stream.** The link check uses the guarded public extractor (no cookies or sign-ins). A channel
  that is not live yet (yt-dlp `UserNotLive`, or a page still showing its last ended broadcast) waits for the stream
  to start, for up to a day after you added it; then the input fails with "add the link again".
- **Recording and clipping.** The recorder (FFmpeg in its own process) writes one-minute segments. Live Monitor has
  three lanes (`queue.WORKER_LANES`), so up to three streams are transcribed, searched and clipped at the same moment;
  more streams keep recording and take turns. A turn never lasts long (`TURN_SECONDS`), and one stream never runs two
  turns at once. Strong moments from the last 15 minutes become vertical clips as the stream runs.
- **Uploads during the stream.** While recording there is no original file yet, so the request is bound to the
  stream's recording project (`submissions.bind_live`). Each upload is still bound to the exact clip file that passed
  its final checks. When the stream ends, the joined recording's path and SHA-256 are bound
  (`bind_live_recording`) before the full-recording analysis (`post_live`, now on the Deep Clip Analyzer, so it never
  holds a live lane). Timing follows the posting settings: with no daily limit or target, a clip goes out as soon as
  it passes, and later ones at least **Minimum gap** apart (30 minutes by default) per YouTube account, shared by all
  streams. A live clip that is approved, uploading or uploaded is never replaced by a better post-live cut.
- **Fewer, stronger clips.** Each stream has its own **How picky** choice, made when you add it (what a new stream
  starts with is in Settings → Advanced → Autopilot details). **Only the best moments** (the default) listens for six
  minutes first, then makes at most about three clips for each recorded hour, at least three minutes apart. A moment
  has to be clearly above the minimum quality and beat most of what this stream has given so far, and the bar rises
  with every clip already made in the last hour; when a strong moment has just happened ClipForge waits up to two
  minutes in case a better one follows; the moment it waits for is remembered from one minute to the next and rated
  again, so waiting never loses it (`live_pick.keep`). Only a standout moment (15 points above the stream's own bar)
  may be a fourth clip of the hour or come sooner than three minutes after the last one; before six minutes of the
  stream were rated there is no such bar, so nothing counts as a standout yet. **Balanced** makes about six an hour,
  each above the stream's average. **Every good moment** makes a clip for every moment that passes the minimum
  quality, as before. The live score is the Clip Score estimate plus how lively the moment sounds (louder than the
  stream usually is, a rising or emphatic voice, laughter); to hear that, each recorded minute's sound is kept as a
  small file for the rolling 15 minutes and deleted afterwards. The stream's card says in a line why nothing is being
  made right now. The full-recording check afterwards keeps the same minimum and the same pace over the whole stream
  (`autopilot/live_pick.py`). All scores are estimates.
- **The whole moment, not its strongest lines.** A moment is found as its strongest few sentences, which used to
  make clips near the shortest length allowed: the punchline without what led up to it. For each moment the picker
  now also looks at fuller versions (more of what was said before it and after it, never across a change of subject
  or a silence of more than three seconds, never over your longest clip length) and clips the fuller one when its
  live score is about as strong: every second a version is short of the length you aim for (Settings → clip length)
  counts like 0.15 points, so the build-up and the ending are kept unless they cost more than about four points. A
  moment that falls apart when it is made longer stays as it was found, and so does one whose fuller version is
  under the stream's minimum, and a fuller version never shows more of a clip already made than the moment itself
  does. The clip's reasons then say *Kept the build-up and the ending: 79 s instead of 45 s*
  (`live_pick.fuller`, `live_pick.ranked`, used in `live.detect`). Live clips follow the same clip length settings
  as every other clip; there are no separate live lengths.
- **Split view.** Each stream also has a **Split view** choice: *when there is a face cam* (the default), *always*,
  or *no split view*. When ClipForge finds a face cam laid over the picture (`pipeline/reframe.find_cam`), the clip
  shows the face cam across the top, a strip for the headline and the captions under it, and below that the
  **whole picture** at full width, nothing cut off, over a blurred fill (`reframe.split_panels`). Settings →
  Defaults → **Under the face cam** switches new split views to *Zoomed in* (the picture's middle fills
  everything under the cam, captions on the line between), and the clip editor has the same choice for one clip.
  Without a face cam the clip uses the layout from Settings. This also fixes clips that used to park on the corner
  holding the face cam. Split view is not only for streams: any clip whose layout nobody chose (no choice in the
  clip editor or for the video, no Brain note, style or skill that decides the layout) looks for a face cam and
  uses split view when it finds one. Settings → Defaults → **Split view** → *Off* stops that for new clips. A clip
  that was already rendered keeps the look it was made with when it is rendered again (a caption fix, a version), so
  a clip made before split view existed is not turned into one, and the clip editor shows what a new render gives;
  the same holds for *Under the face cam*.
  An Autopilot plan keeps its layout without a face cam and its *Under the face cam* choice. In the clip editor,
  Layout offers **Split view** and **Split if face cam** for any clip; choosing **Framing follows** something other
  than automatic gives one picture placed as asked (the Layout shown changes with it), unless a split view is then
  picked again. Captions placed at the top go on the line between the pictures, never on the face cam. A stream that
  was being recorded before this update keeps the layout from Settings, as its card says (*No split view*).
- **Split the clips between channels.** With two or more YouTube channels ticked, the request asks how the clips are
  shared: **Every channel gets every clip**, or **Split the clips between the channels**. Split means each clip is
  uploaded to one channel only; the channels take turns (the one with the fewest of this stream's clips goes next;
  on a tie, the one with the fewest clips over all your videos and streams that split their clips, then your ticking
  order), so no clip appears on two of them and streams with one clip each still share the channels. A clip never
  changes channel once it has a planned post or was uploaded there by hand, and a channel that needs Reconnect is
  passed over until it is back. The agreement text names the choice, and the videos and streams lists say *taking
  turns*. Submitted videos have the same choice (`submissions.clip_turn`, stored as `settings.split = "turns"`).
  Known limit: a clip waits for its own channel; when that channel's planning days are full (only possible with a
  daily limit set), it is not moved to the other channel.
- **Stop clipping** (on the card of a stream that is recording, with a confirmation) is for when you have enough:
  the recorder stops, no more clips are made now and the full recording is not searched for more. Everything already
  made stays exactly as it is: clips keep their final checks, planned posts keep their times, and with Make & upload
  they still upload. It cannot be undone for that stream (Try again does not take it back); add the link again to
  clip the channel from then on. Nothing is canceled or deleted.
- **Stop recording** (on the stream's card, with a confirmation) stops the recorder, joins what was recorded and
  analyzes it like an ended stream; the uploads made so far stay, and so do the live clips, except that the
  full-recording check may swap one nobody approved for a clearly better cut of the same moment (see above). Before
  anything was recorded it ends the input. It works while Autopilot is paused, and never contacts the platform.
  **Cancel stream** still cancels. The dialog says that a YouTube video link cannot be added again; the stream's card
  offers "Add the link again" only for channel pages and stream addresses (`submissions._finished_broadcast`).
- **Recording limits.** Every live recording stops at **Largest source** (Settings → Advanced; 8 GB and 240 minutes
  by default), even while the stream is still live, and is then finished like an ended stream (shown as Stopped).
  The Live streams page names the owner's current limits under the link box.
- **One broadcast per input.** A channel that goes offline after recording started gets 5 minutes' grace (a dropped
  connection), then the recording is finished. If a channel page shows a different broadcast (a new broadcast id, or
  a gap of more than 5 minutes that cannot be shown to be the same broadcast), the recorded one is finished and not
  extended. A gap while ClipForge itself had stopped the recorder (a pause, closing, disk space) counts from when it
  stopped it. A link to one stream (a live video, an `.m3u8` address) is that stream however long the gap. Add the link again for the next broadcast: once the earlier recording has finished, the same link makes a
  new input with a new request (`external_id` ends in `:<previous input>`), and the earlier input can no longer be
  retried. Twitch and Kick links are compared in one spelling (`www.`, `m.`, case and a trailing slash ignored).
- **Staying up.** A minute that waits more than 45 seconds for the GPU hands its turn to another stream and is
  transcribed on a later turn (`Wait("gpu")`); the recorder keeps recording. An unreadable minute stays on the
  timeline and is transcribed in the full-recording pass. Joining places every minute by its recorded length (the
  recorder's segment list), not its file's length, which with stream copy runs some 40-70 ms past each cut and would
  add up to seconds over a long stream; each minute but the last also ends there, so media past it (sound after a
  stalled picture) never overlaps the next minute. When some minutes have no sound, or a reconnect changed the
  sound's settings (each minute's are saved), the picture is still joined by stream copy and the sound is rebuilt
  minute by minute exactly as each was heard live, then encoded once (a stream copy keeps only the first minute's
  tracks and settings). Live clips use the same join for the minutes around their moment, so a clip right after a
  minute without sound keeps its sound. It leaves out a minute FFmpeg cannot open and keeps its time as a gap, so
  every later time still matches (FFmpeg would otherwise skip it and still report success); a minute found broken
  only then is transcribed again in the full-recording pass. A join that FFmpeg still cuts short, or a recording
  whose first minute cannot be read, stops with a clear reason and keeps the live clips. A moment whose plan or
  render failed is not tried again on every later minute. The recording size limit (also through the stream relay) and a recorder that keeps failing
  after minutes were saved finish with what was recorded instead of failing. A dropped connection after recording
  reconnects without using an attempt. A stream that starts or reconnects reserves the remaining recording size of
  the streams still recording on disk (room checked earlier may since have been taken, for example by a stream that
  started while this one had no recorder); streams starting at the same moment count each other, so two links added
  together never both start on a disk with room for one, and a link still being looked up (it may be offline) holds
  no room. **Stop all jobs** holds recordings (the recorder stops;
  nothing is canceled); **Resume** continues them from their saved minutes, including a held full-recording analysis.
  A turn that was still running when Resume was pressed ends held and the worker supervisor continues it within
  30 seconds. A turn that ends with a retry or a crash after Stop all jobs (or Cancel, or its time limit) arrived is
  held, canceled or failed accordingly, never left waiting with a stop request no worker would take (all job kinds).
  Stop all jobs never turns your own Cancel of a running job into a hold, and Cancel pressed after the time limit
  stays a cancel. Once the full recording is queued for analysis, another turn of that stream never reopens or rewrites
  the recording's files (only Try again after a failed analysis whose joined file is gone records the join again).

What is not tested from the cloud: real Twitch, Kick and YouTube broadcasts (YouTube cannot be reached from the
build machines), and whether CPU Whisper on a Mac keeps up with two or three streams at once. The tests use local
streams played at real speed (`tests/test_review_submitted_live.py`, slow `tests/test_review_submitted_live_streams.py`).

### Optional discovery and earlier intake tools

Select **Discover videos** explicitly to use searches, watched folders, channel lists and live monitoring. The
older three-step setup and **Open videos folder** tools remain for that mode. Starting Autopilot in the default
submitted mode does not create an automatic Owned folder rule or admit its files. Existing folders and their
files are preserved. Old standalone link/live tools do not create a new Make & upload request; in submitted mode,
use the new Missions forms for new recorded inputs and live streams. Discovery keys and access/reuse rules remain separate from
upload authorization. Streams retain their existing bounded capture/public-archive recovery and restart behavior.

**Keeping the PC awake.** While Autopilot is on, ClipFoundry asks Windows not to put the PC to sleep (the screen may
still turn off). The request ends by itself when ClipFoundry closes. A laptop still sleeps when you close its lid.
Settings → Advanced → Autopilot details → *Keep the PC awake* turns it off. On macOS and Linux nothing is changed.
Autopilot → Overview says what is really happening (the *This PC* fact and the note under it; `home.keep_awake`, from
`awake.KeepAwake.status`), not what the setting asks for: *Kept awake* (*is keeping this PC from going to sleep*)
only after Windows accepted the request, *Asking Windows* for the few seconds before that, and when Windows refuses,
*Windows said no* (*did not let ClipFoundry keep this PC awake*) with a Needs you item that says how to turn off sleep
in Windows' power settings. It asks again every minute (not every few seconds), the refusal is logged once (Autopilot
→ Advanced → System → *Recent events*), and the item goes away by itself when a retry works or Autopilot or the
setting is turned off. The same app thread asks and gives up the request, because Windows ties it to that thread.

For optional discovery with review mode deliberately off, turn on **automatic publishing** afterwards (*Turn on
automatic publishing…* under *How posts go out* on Autopilot → Overview, or in Settings → Accounts → YouTube). It
shows exactly what you allow: the channel, what gets posted (only clips that passed every check, from videos you own
or that an agreement or license covers), who can see the posts, made for kids or not, how many a day and between
which hours, and you confirm it. Turning it off (*Turn off…*) sends every post it approved that has not started
uploading back to Posts → *Needs review*, where it waits for your OK. Permission is bound to the connected channel
and confirmed audience: new Public uploads require fresh Public permission; existing Private posts stay Private.
Selected-viewer Private uploads still need you to share them in YouTube Studio. Public posts need no invitations.

The default posting window is **0–24**, with no app daily cap or forced spacing. Eligible approved clips get the
earliest permitted time, and the upload worker serializes its actual work. Platform/API waits, quality, reuse and
duplicate checks remain active. Existing scheduled posts retain their times and audiences. This update applies
a one-time recorded volume/hours amendment to existing YouTube permission; it never creates a missing grant.
Optional positive limits chosen after the update persist across restarts. For long-running Google access, an
External OAuth app in Testing has
seven-day refresh grants for YouTube scopes. Set its OAuth publishing status to Production, then reconnect for a
fresh grant. Personal-use apps may be exempt from OAuth verification; Production and API quota audits are separate.
Authorization can still expire or be revoked. [UNATTENDED.md](UNATTENDED.md) covers the optional app-exit watchdog,
same-user Windows login startup and local diagnostic logs. It preserves intentional Pause/Stop and consent holds.
Run only one app per data profile, including across different ports. The watchdog detects process exit, not a
still-running hung main app.

Both platforms only let apps like ClipFoundry post through *your own* free developer app, so the first **Connect
YouTube** or **Connect TikTok** on a computer asks for that app's two codes once (the steps are under *How to get
these codes*; see also [INSTALL.md](../INSTALL.md)). After that, **Connect** is just the platform's own sign-in page.

**TikTok form help.** In Settings → Accounts → TikTok, open **Help me fill out the TikTok app form**. It provides
copyable app details, 1024 × 1024 PNG icons, the current-port Login Kit Desktop callback, scope explanations and a
demo checklist. Choose **inbox**, **Direct Post only** or both; posted-video statistics are optional. Apply the
permission choices, save Settings and reconnect. Previously granted permissions remain until you reconnect.
Existing installations keep their earlier posting choices until you change them.

The helper's website fields and checklist stay in memory in this app tab until reload or close, and survive saving
Settings. **Download TikTok form pack** explicitly exports those fields with app details, icons and draft static
website/legal pages. Invalid entered website addresses block the download; correct them or leave them blank for
an incomplete draft. App codes, tokens, account identities and media are excluded. It does not submit a form,
publish pages or verify a domain. Review the draft pages before publishing; TikTok requires a real developed
public website with visible active policy links and URL ownership verification. The Desktop loopback redirect is
a separate local HTTP address. See [TIKTOK_APP_SETUP.md](TIKTOK_APP_SETUP.md).

Completing the form does not make a personal utility eligible for TikTok production review or lift an audit
restriction. Sandbox is for target-user testing and cannot post Public videos. Unaudited Direct Post requires a
private TikTok account and Only me. A private profile cannot offer Everyone; each upload still needs your consent.
If TikTok does not approve the app or grant a posting scope, use the ready-to-post package and post it yourself.

In optional discovery mode, the advanced source system uses configured services and folders (the
connected YouTube account for discovery; your videos folder; other watch folders and feeds only if you added some;
Google Trends and TikTok trends are not available to apps and are skipped without bothering you) and these defaults:
United States, English, your topics, no app daily source/upload cap, up to 5 best clips per source,
posting at the earliest eligible time (America/Chicago, any hour), recurring searches (within 15 minutes when
there is queue capacity, otherwise the saved regular interval), dynamic replacement, live monitoring, learning,
automatic scheduling and automatic publishing of the
posts that are approved. Autopilot is turned on and off with **Start Autopilot** / **Pause Autopilot** on the
Autopilot page; Settings → Defaults has the optional daily clip cap, posting hours and topics, and Settings → Accounts
has automatic publishing; everything else is under Settings → Advanced.

**The Autopilot page** has four tabs. **Overview** shows only: whether Autopilot is on, with **Start Autopilot** /
**Pause Autopilot**; four facts (*This PC*: whether it is kept awake; *Processing*: the GPU or the CPU; *Next online
search*: when it next looks for new videos online; *Your videos folder*: whether it is checked) and a reminder that
the PC must stay on with the ClipFoundry window open to find and render clips, and when posts go out (a YouTube post
that was already uploaded goes out at its time even if the PC is off; TikTok posts need the PC on at their time);
**Needs you**; **Working on** (what Autopilot is doing right now, step by step); **Your videos** (how many videos your
videos folder holds, whether it is watched, *Open videos folder* and *Show folder location*); **Coming up** (the
upcoming posts) and **How posts go out** (automatic publishing, and whether YouTube and TikTok are connected); and
**Pause or stop everything**. **Activity** has the top opportunities it found (*What Autopilot found*) and the
activity log (what it did with each video it found and why it skipped any). **Permissions & sources** has creator
agreements, watch folders, feeds, permission rules and every video it found. Workers, quota, jobs, today's numbers
against the target, the next post, scores and learning are under **Advanced** (System, Jobs, Learning). **Home**
shows the most urgent thing that needs you, your recent videos and clips, and the next posts.

**Needs you** (on Autopilot → Overview; Home shows the first item) lists only what really needs you, in plain words:

| What | When | Your answer |
| --- | --- | --- |
| *ClipFoundry found a strong trending video. Can you use this content?* | **Off by default.** Only with Settings → Advanced → Discovery and rights → *Ask me about strong videos nothing covers* turned on: only while today's plan is short, only for strong videos (Source Score 50 or more), at most 3 at a time. | **Yes, I have permission…** (recorded as *Allowlisted* for that video, with the date), **No, don't use it** (*Blocked*, never asked again) or **View the video**. Only say yes when the creator gave you permission; being public or trending is not permission. |
| *N posts waiting for your OK* | TikTok posts always; YouTube posts unless automatic publishing is on (and clips it holds for you because a check noted a possible problem). | **Review posts** opens Posts → Needs review. |
| *Reconnect YouTube / TikTok* | The platform refused the stored sign-in, or it is not connected while posts are planned there. | **Reconnect YouTube** / **Reconnect TikTok**. |
| *GPU transcription is not working* | Strict GPU paused transcription. | What to do is shown with it; **Open GPU settings** opens Settings → Advanced. |
| *Your PC may go to sleep and stop Autopilot* | Autopilot and *Keep the PC awake* are on, but Windows refused to keep the PC awake. | Turn off sleep in Windows' power settings (the steps are shown with it). It goes away by itself when ClipFoundry's next try (every minute) works. |
| *Autopilot needs videos to work with* (or *has used all your videos*) | Autopilot is on and has looked, but nothing it may use is waiting or being clipped, and it made no clip in the last 24 hours. It says how many videos it skipped because they belong to other people. | **Open videos folder**, then put videos you made in it (or **Add a video yourself**). |

Quota notices resolve themselves and stay under Autopilot → Advanced → System. A video nothing covers, or whose file
cannot be obtained in an allowed way, is not a question: it is skipped, listed in Autopilot → Activity with the reason
(with *Add the file…* when you could supply the original), and Autopilot moves on to the next one.

**Adding content by hand** stays possible and optional: under Autopilot → Permissions & sources, *Add…* → *A video,
link or folder of yours…* (a link, a file on this computer, a folder to watch, or *Upload a video*, which opens the
Add video page), with one question, *Can ClipFoundry use it?*: it's your own content, you have the creator's
permission, or you're not sure (then it isn't used until you decide).

### Hands-off discovery, eligibility and files

**Discovery** runs repeatedly within the providers' quotas and your cost limit. With queue capacity and remaining
configured source allowance, it checks again within 15 minutes; busy queues retain the regular interval (three
hours by default). A YouTube quota or Retry-After wait stops that provider's requests while independent searches
and free folder/feed checks continue. Saved active candidates are reconsidered on the free feed cadence.
YouTube and Commons rotate through at most five result pages per query, one page per normal pass; they do not
repeat only the first page indefinitely or add an unbudgeted burst of calls.

**Quality first** is enabled by default. Missions → Permissions & sources → **Quality before quantity** controls
the small broad-search shortlist: **3 new strong candidates per pass**, at most **6 workable unfinished picks**,
and at most **1 per known creator per pass**. Videos waiting for permission or a file stay saved and do not block
accessible videos covered for a connected, enabled publishing destination. New local-only or waiting finds still
use the combined backlog limit, keeping new parked finds bounded; saved parked records plus workable picks may
exceed six. Existing work and history are retained. Within the quality floor, available reuse-covered videos take
precedence over local-only finds, including candidates saved by an earlier search. Explicitly chosen input keeps
its priority. The shortlist also spreads topics and filters probable duplicate uploads. The configured
daily source limit is optional (**0 means unlimited**). With no app daily cap, completed work frees capacity for
more strong eligible sources; the six-workable-pick bound, per-search shortlist and API/cost allowances still
prevent unlimited queue growth. A positive source cap counts weak/failed attempts and resets next local day.
Old inactive local-only picks do not occupy uploadable-source capacity. Held candidates can compete in later
passes; low-scoring finds never lower the quality floor to fill an optional cap.

**Find videos eligible for uploading** is on by default. Own/agreed channels are checked before broad-search
quota is used; broad YouTube topic searches request Creative Commons and actual metadata still verifies each
video's license/channel. Free-license library downloads and creator-provided originals remain valid paths.
Missions explains local-only finished clips and links to original videos, recorded creator agreements and the
free-license library. A new agreement must cover the destination; its required attribution is checked against
actual post text. Choosing local-discovery mode does not remove any upload check.

Manual links/videos, owned folders, recorded creator agreements and channels or feeds the owner chose retain
their existing intake path. They bypass the broad-search admission and attempt limits; rights, media access and
final quality checks still apply. Quality mode does not delete saved sources or cancel work already underway.
Missions → Activity shows admitted, held and filtered counts with reasons. Source scores estimate promise from
available signals; only transcript analysis and the final-file gate can establish usable clip quality.

* **YouTube** (Data API search and video details, the connected account or an API key): recent popular videos for
  your topics, and the **original long video behind a popular short clip** when the clip links to it or its channel
  has it.
* **Web search** (optional, [Tavily](https://tavily.com), your own API key under **Settings → Integrations → Search
  connections**, also available under Missions → Permissions & sources → Quality before quantity → *Find better
  links with a free search key*): public TikTok links for your topics and originals behind clips. Web search
  gives titles and links, never TikTok statistics: those stay *unknown*. It uses the credits your plan includes (the
  [free plan](https://docs.tavily.com/documentation/api-credits): 1,000 a month without a credit card) and spends
  money only up to the monthly cost limit you set
  (0 by default: never). Keep the budget at $0 to stop at the configured included allowance. The optional key can
  improve search coverage; it does not guarantee stronger clips or supply reuse permission. YouTube discovery can
  use a connected account or your own free YouTube Data API key. Local files need neither search key.
  Search connections provides official key-creation steps and a **Use free Tavily plan limits** button. Save the
  settings afterward. Included credits are a local app allowance, not a live provider balance; saving a key does
  not test it or connect an upload account.
* **A free-license library** (Wikimedia Commons, on by default): videos whose authors released them for reuse.

Duplicates and re-uploads of videos already processed are dropped. Every number keeps where it came from and when it
was observed; ClipFoundry's own scores are labeled as estimates.

**Eligibility without per-video questions.** A video is used automatically only when something real covers it, and
the evidence and conditions are stored with it (`autopilot/rights.py`):

* your own content (*Owned*);
* a **creator agreement** you record once (Autopilot → Permissions & sources → *Record an agreement…*): the creator,
  their channel IDs or handles, what shows the agreement, and its conditions: credit line, commercial use, which
  platforms, end date, and whether it also covers other people's music or footage in their videos (by default it does
  not, and a clip with detected music under such coverage is rejected);
* a license that allows it: **CC BY** (a credit line is added to the description; share-alike, non-commercial and
  no-derivatives licenses are never used automatically) or **public domain / CC0**, as the library reports it.

Anything else is skipped and listed in Autopilot → Activity. Cropping, captions, a credit or a short duration never make
something usable, and no score is treated as legal clearance.

**Confirmed channels** (`autopilot/verify.py`). A channel named by a feed, a web search or any list is only a claim.
Before your own channel (*Owned*) or a channel rule or agreement is applied to a video, the platform itself must
confirm that this exact video belongs to that channel: YouTube through the Data API (a video Autopilot found through
the Data API already carries YouTube's answer; any other one costs 1 quota unit per 50 videos), TikTok through its
embed API (oEmbed), which answers by the video's number whatever name the link shows. The link the file would come
from must lead to that same video. A confirmed channel still has to match one of your rules or agreements:
confirmation only says who posted the video. A video that cannot be confirmed (another channel, a link to a different
video, a platform ClipFoundry cannot ask, YouTube not connected) is skipped with *channel not confirmed* and the
reason in Autopilot → Activity, and asked about again later (after 1 hour if the platform was busy or not connected,
after 1 day if the video was not found). The check runs again before every stage, so a video queued earlier cannot
get around it, and a feed can never overwrite what the YouTube API reported about a video.

**Getting the file** (`autopilot/access.py`) is a separate check: a file on this computer, the folder a creator shares
with you (named in the agreement; the file is found by the video's YouTube ID in its name, or by its title, once it has
finished syncing), a file link under the address the creator gave you, the library's own download, or a direct link
you configured. Each file is stored with a provenance record (where it came from, how it was obtained, the rights and
evidence, the license and credit). If there is no allowed way, the video is skipped and the next one is tried.

### Advanced setup (optional)

Everything from before is still there for advanced users:

* **Where videos come from** (Autopilot → Permissions & sources, *Add…* → *A channel, stream or trend list…*):
  *folders* of your own recordings (a file that is still growing is treated as a live recording), *YouTube channels*
  you follow (`UC...`), *streams* you may use (HLS/RTMP/SRT), and *trend lists* (JSON/CSV) you are authorized to use.
  A folder, channel or stream you add can carry a permission; a trend list row's channel is a claim that must be
  confirmed (above).
* **Permission rules** (same page, *Add rule…*): channels whose clipping program you joined (*Allowlisted*), licensed
  feeds (*Licensed*), folders of your own recordings (*Owned*), or anything you must never use (*Blocked*), each with
  its basis. Anything without a rule or an answer waits for you.
* **Discovery** (Settings → Advanced → Discovery and rights): a YouTube Data API key instead of the connected account,
  region, language, how often to look and how old a video may be. The topics are on Settings → Defaults (*Topics to
  look for online*).
* **Schedule and limits** (Settings → Advanced): *Autopilot details* has the time zone, sources per day, clips per
  source, minimum quality, platforms, replacement, live monitoring, learning and the worker process; *Autopilot
  posting* has the minimum gap and the per-platform daily limits; the quotas are under *Discovery and rights* and the
  GPU under *Transcription and GPU*. The active hours are the posting hours on Settings → Defaults.

The worker runs in its own background process by default (Settings → Advanced → Autopilot details → *Worker
process*: *Own process*), so a crash in a worker cannot take the app down. It is started and stopped with the app:
when the app closes, the worker notices the missing heartbeat and exits within a minute. It can also be started on
its own with `python -m clipfoundry workers`.

## How it works

The default path is:

```
Submitted link/file → acquire original → relevant Brain guidance + Settings → select/render clips
  → grounded packaging → exact-file/text Quality Gate → source-scoped approval → local due time → YouTube
```

**Make clips only** stops before scheduling. The workers below are reused by both modes; Trend/Source Scout,
free-feed admission and Live Monitor polling run only in optional discovery mode. Historical source-count examples
are not current default daily caps. The optional discovery path is:

```
Trend Scout ─┐                                   ┌─ Live Monitor (live sources, rolling window, post-live pass)
Feeds ───────┼─> Source Scout ─> Rights Gate ─> Clip Hunter ─> Deep Clip Analyzer ─> Diversity Selection
             │                                                                          │
             │                                               Packaging AI <─────────────┘
             │                                                    │
             │                                            Final Quality Gate (file + text)
             │                                                    │
             │                   Smart Scheduler (America/Chicago, limits, replacement)
             │                                                    │
             │   Approval: manual review, or standing YouTube permission when review mode is off
             │                                                    │
             └────────── Learning Worker <── real results <── Publisher (official APIs, resumable, idempotent)
```

| Worker | Job kinds | What it does |
| --- | --- | --- |
| Trend Scout | `trend_scan` | Reads YouTube search/chart results (within its quota share), feeds and watch folders. Stores every signal with its history and a Trend Score. Metrics carry their provenance: *observed*, *estimated* or *unavailable*. |
| Source Scout | `source_scout`, `feed_scan` | Turns signals into sources, scores them (Source Score, expected strong clips) and picks up to 3 per day, skipping duplicates, weak and unavailable ones. |
| Rights and Content Safety Gate | `rights_check` | Applies your rules, agreements and licenses. Only *Owned*, *Licensed*, *Allowlisted*, *Creative Commons* (CC BY) and public-domain sources continue automatically (each kind can be turned off in Settings → Advanced → Discovery and rights → *Use automatically*); everything else is skipped and listed in Autopilot → Activity. The gate runs again before every later stage, before scheduling and before publishing, so a later *Blocked* rule stops a post and a source queued before a check cannot skip it. Channel claims are confirmed first (see *Confirmed channels*). |
| Live Monitor (3 lanes) | `live_watch`, `live_capture` | Records authorized live sources in segments, transcribes each segment (one GPU job at a time; a minute that waits more than 45 s hands its turn to another stream), and clips strong moments from a rolling 15-minute window. Three lanes work on three streams at once; more keep recording and take turns. When a stream ends it queues `post_live` for the Deep Clip Analyzer. |
| Clip Hunter | `hunt_source` | Brings the source in (hard link or copy of a local file, a direct media URL, or the URL importer only when allowed), transcribes on the GPU and builds a large candidate pool. |
| Deep Clip Analyzer | `analyze_source`, `regenerate_clip`, `post_live` | Fast filter → semantic analysis → deep evaluation (Viral Potential, audio and visual features) → boundary optimization → diversity selection (MinHash text and perceptual video fingerprints against everything already made). Then the **Engagement Strategist** writes a Clip Blueprint for each chosen clip (see below) and the clip is rendered from it. Renders up to 5 clips that pass the quality bar. |
| Packaging AI | `package_clip` | Writes title/description/caption/hashtag options in six styles from the words heard in the rendered clip (its final transcript), optionally with an AI provider, validates grounding, repetition and duplicates, and scores them. Each option records which render it was written for. |
| Final Quality Gate | `quality_check` | Checks the exact file that would be published: SHA-256 against the render record, streams and codecs, 1080×1920, duration, a full decode (a truncated file still reports its full length), black, frozen and silent stretches judged in context, caption timing, cuts inside words, and the hook/context/payoff estimates. Re-checks each platform's selected text against what is heard in that file. The report is bound to the file's hash, final transcript and time map. Failures keep the clip out of the schedule; warnings are shown with the post. |
| Smart Scheduler | `schedule_tick` | Places packaged clips whose current file and text passed the Final Quality Gate on each platform's time grid within your active hours and limits, computes the Final Opportunity Score, replaces weaker unpublished posts with clearly stronger new ones (a slot is swapped at most once every 24 hours, and it never has more than one swap waiting for your approval), and hands due approved posts to the publisher. |
| YouTube Quota Manager | (inside every YouTube call) | Counts units and calls per bucket, keeps discovery within its share, and reserves the rest for uploads, statistics and account checks. Resets at midnight Pacific. |
| Publisher | `publish` | Hashes the file again and needs a passing Final Quality Gate report for exactly those bytes, then uploads approved posts with the existing YouTube and TikTok code. An interrupted upload resumes its stored session (YouTube) or checks its publish ID (TikTok) instead of posting twice. If the platform accepted every byte but its answer was lost and it can no longer say what happened, the post is never uploaded again automatically: it becomes *Upload not confirmed* until you check (the video is looked for among the channel's newest uploads first). **Waits** are never shortened: when YouTube or TikTok asks to wait (`Retry-After`, or 60 s for a rate limit that gives no time), up to 60 s is waited out in place; a longer wait puts the post back for exactly that time (no attempt used), holds the platform's other posts until then, and the same upload continues afterwards. |
| Learning Worker | `learn` | Reads the real results of your posts (snapshot near 48 h), and once there are at least 10, adjusts posting-time lifts, style bonuses, score weights and the retention estimate, using only groups with enough data. |
| Maintenance | `maintenance`, `selftest` | Recovers stale jobs, applies the YouTube 30-day data rule, cleans caches. |

**Durable jobs.** Every job is a row in `worker_jobs` (SQLite) with a state (`queued`, `running`, `waiting`,
`completed`, `failed`, `canceled`, `retrying`), an idempotency key, a lease that the worker renews, a timeout, attempt
counts and a structured log (`job_logs`). Claims are atomic (`BEGIN IMMEDIATE`). If the app, the worker or the PC stops,
leases expire and work can resume/retry after restart, using its idempotency key and saved state to avoid duplicating
completed work. Saved upload sessions and uncertain-outcome holds prevent blind repeat uploads.
Jobs you start by hand (for example *Clip now*) run even while Autopilot is off.

**Teaching the Brain.** Open Brain for the Obsidian-inspired graph built from saved notes, examples, topics,
active clip preferences and recorded results/influence. Search or click a node to inspect what it actually
contains; graph links represent saved relationships and evidence, with coverage limits shown. Pan, zoom, fit and
motion controls make it inspectable without changing work.

**Add note** saves a local reference. **Teach preference** saves supported clip choices. Saving an enabled lesson
activates recognized guidance automatically for new clips, with Settings supplying missing choices. Topic matching
uses the source title and spoken words; the context follows each candidate into planning and rendering. **Add
example** stores a good or bad example with its explanation. Recognized feature descriptions can change caption/
pacing choices and ranking; good examples also supply a measured length hint, within your configured length range.
Bad-example observations are not promoted as positive traits; use corrective preferences to change future edits.
The editor shows recognized effects. Unsupported notes stay searchable without changing edits. More options keeps
file imports and detailed fields accessible. Saving or importing does not infer video appearance, fine-tune a model
or execute uploaded code. Decisions shows actual influence; Performance retains real results and their provenance.
Explicit clip-editor choices win, and existing rendered clips keep their previous plans.

**Recovery and resource limits.** Failed worker initialization stops partially started workers before releasing its
host lock. Job setup failures clear their running/heartbeat entry instead of retaining a phantom lease. Media
subprocess timeouts and cancellation can interrupt blocked pipe reads/writes and waits, killing and reaping the
children. Disk checks keep a 2 GB reserve: unknown-size downloads budget for their configured maximum, and live
capture rechecks free space while recording. Low disk shows Needs you and a durable 30-minute wait, retaining saved
segments and completed files; it is not treated as the stream ending. Final assemblies replace a completed recording
only after the temporary assembly succeeds. No owner media is automatically deleted to make room.

Before a new scheduled upload session begins, Pause, applicable input/post/standing authorization, account/audience and final-file checks
run again even if a local publication row already exists. A valid existing session continues with its original
confirmed bytes. Final-chunk crashes, cancellation or ambiguous platform replies retain an unknown-outcome hold;
later reconnect, setup, scope and quota errors preserve that hold and publication identity after final-byte evidence.
Recovery requires an original-account, unique recent match with the submitted title, description and tags, then
reads actual returned visibility. A mismatch stays held for the existing Queue resolution; a restart grants no
permission to upload another copy. Manual unknown uploads expose **Refresh status** without starting a transfer.

**Clip Blueprint.** Before a clip is rendered, the Engagement Strategist stores a typed, versioned plan for it
(`pipeline/blueprint.py`, table `clip_blueprints`, `blueprint.json` next to the render): the source intervals in
seconds of the original, speed, framing, captions, the words to stress, audio adjustments, the hook and the payoff
line, and why the moment was chosen. A plan the renderer could not follow faithfully is rejected before rendering
(intervals outside the source, reversed, overlapping or out of order, a cut inside a word, unsupported speed or
options, emphasis outside the kept intervals, on-screen text that is not said in the clip). Instructions the renderer
does not support are listed as unsupported and left out, never claimed as applied. The renderer follows the plan
exactly and records the plan's hash with the file; your edits and alternative versions are applied on top as a new,
stored plan. Manual projects have no plan and render as before.

**Cutting out weak middle parts.** The Strategist may cut up to two weak sentences out of the middle of a clip:
sentences made only of filler words ("Um, you know, like, yeah."), a clear promotional line ("Subscribe to the
channel for more.") or a warm-up phrase that says nothing of its own ("So anyway, moving on."). It cuts only when
every rule for a safe cut holds: a pause on both sides, complete sentences, the next sentence does not point back at
what was removed ("It has ten lessons."), the hook, payoff, questions and the first and last sentences stay, at most
35% of the clip goes, and the clip stays at least as long as the shortest clip you allow. Otherwise the clip stays
one continuous piece. The order never changes. The final transcript, the captions, the post text and the final
check all follow what is heard in the cut clip, and the plan's reasons say what was cut.

**GPU.** One heavy GPU operation at a time, across processes (a lock file), with a wait for free VRAM
(Settings → Advanced → Transcription and GPU → *Free GPU memory needed*). Transcription uses exactly the existing
faster-whisper/CTranslate2 CUDA path; Autopilot only waits for its turn. **Strict GPU:** when an NVIDIA GPU is expected
and CUDA fails (or the GPU is present but unusable), Autopilot does not fall back to the CPU: the job pauses for 30
minutes without using an attempt and an action item says what failed and how to fix it. Live capture keeps recording
meanwhile; the post-live pass transcribes the whole recording again on the GPU. Settings → Advanced → Transcription
and GPU → *Allow CPU transcription in Autopilot* lets it continue on the CPU instead (slower). Manual projects keep
their visible CPU fallback. Local AI models (Ollama/LM Studio) share the same lock.

**Downloads and addresses.** Autopilot fetches media and signals from URLs that come from data (a feed's rows, a
discovered source, a redirect), so every such URL is checked first (`netguard.py`): only http/https for downloads and
network stream protocols for live capture (never `file:`, `concat:`, `pipe:` or `data:` in ffmpeg), and the host
must resolve to public addresses. Addresses you typed yourself (a source added by hand, a stream you configured, a
signal feed's own URL) may point into your own network. Every redirect is checked, a download connects to exactly the
address that was checked, and it stops at Settings → Advanced → Autopilot details → *Largest source* (8 GB and 240
minutes by default; longer videos are not processed). A download that would leave less than 2 GB free on the data
drive waits with an action item.

## Scores

All scores are 0-100 estimates computed by ClipFoundry to rank opportunities. They are not platform metrics and not
predictions of views.

| Score | Meaning |
| --- | --- |
| Trend Score | How much attention a signal is gaining: velocity, acceleration, engagement, recency, live status, size and recurrence. For YouTube data without Google's derived-metrics approval it is YouTube's own order only. |
| Source Score | How promising a source is: trend strength, expected clip potential (learned yield per minute), creator history, freshness, live status and topic results. |
| Clip Score | Viral Potential of the clip plus bounded adjustments from audio/visual/semantic analysis and trend relevance. |
| Diversity Score | How different the clip is from the other selected clips and from everything you already made. |
| Packaging Score | Quality of the chosen title/caption: curiosity, emotion, clarity, natural wording, platform fit, searchability, uniqueness, click appeal, plus a learned style bonus. |
| Expected Retention | Retention Potential, calibrated with your real average % viewed once enough results exist. |
| Publish Opportunity | How good the planned time is (learned time-of-day lift, gaps, freshness of the trend). |
| Final Opportunity | Weighted sum of the above (clip 35%, packaging 15%, trend 15%, source 10%, diversity 10%, retention 10%, publish opportunity 5%); the weights adapt within ±50% when your results show a different pattern. |

Each planned post's page shows *Why this time and score (estimates)* with the explanation, and *History of this post*
(the audit trail).

## Posts

**Posts** lists every planned and published post (one clip on one platform), in order, with its video, text,
platform, permission, time and final check. Each post opens as its own page with its scores.

**YouTube comments:** Private and made-for-kids videos do not allow comments. Review explains these effects before
you approve. The answer must match the intended audience; malformed strings/numbers are rejected instead of
coerced. Existing upload/status responses show YouTube's returned audience evidence when available. Channel
defaults and platform restrictions may still turn comments off. The upload API has no enable-comments switch;
check Audience and Comments in YouTube Studio for an already uploaded video. Qualifying new clips from an
explicit Make & upload request use that input-scoped authorization; other posts retain manual review by default.
Standing automatic approval applies only if review mode is explicitly disabled.

**Audio:** fresh processing preserves initial audio offsets/gaps and uses one consistent source track. Rendering
downmixes before normalization and applies final peak control after speed/gain. Existing clips and uploads are
not silently rewritten. A distorted original needs a better source; a bad old render needs fresh owner-reviewed
processing and any new upload requires a fresh exact-file approval.

* **Approve for YouTube** / **Approve for TikTok** (on the post's page, after ticking *I watched this video and read
  its text*): posts outside an explicit Make & upload request need your review or applicable standing YouTube permission. For YouTube you confirm the title,
  description, tags, made-for-kids answer and explicit Public/Private audience. For TikTok the page reads creator info
  first, shows your nickname and lets you choose the privacy options it returns, without preselection. Everyone
  needs a public TikTok account and eligible app; followers/friends/Only me depend on the account and app. It also shows
  interactions (off by default), the commercial content disclosure,
  and shows TikTok's Music Usage Confirmation. An approval is bound to the exact video (its SHA-256, not its size or
  date) and text: editing either, or a new render, needs a new approval. A valid source or standing request may authorize a fresh automatic approval after final checks; manual
  edits/cancellation cannot be overwritten by that process. TikTok always asks you.
* On the post's page: edit the text (**Save changes**, or **Save the text without approving**), **Change the
  time…**, **Cancel this post…**, **Try again…**, **Publish now…** (on an approved post), and **Link the post…** for
  inbox drafts finished in the TikTok app. A post's More menu in the list also has **Open the clip**, **Open on
  YouTube** / **Open on TikTok** and **Open the source video**.
* **Upload not confirmed**: the upload may have finished but the platform cannot confirm it (for example **Stop all
  jobs** or a crash during the upload). ClipFoundry first checks with the platform; if it still cannot tell, it waits
  for you: **It's on YouTube: add its link…** (or TikTok) or **It's not there: upload again…** (after you checked
  that it is not there). It never uploads a second copy on its own.
* New confirmed Public YouTube posts upload locally when due, without `publishAt`. Existing Private schedules stay
  Private and may upload ahead of time (default 30 minutes). Selected-viewer posts show *Awaiting viewer invitations*
  until you share them in Studio and press **I shared it**. Legacy unconfirmed public/unlisted plans remain held.
* **Final check**: every post shows the Final Quality Gate's verdict on its exact file and text (*passed*, *passed,
  N warnings*, *failed*, *the text needs a fix* or *not done yet*), with every check listed (*All N checks of this
  exact file*) and marked as measured or as an estimate. A post whose file failed cannot be approved or uploaded; fix
  the clip and render it again.
* Tabs: *Needs review*, *Scheduled*, *Published* (tick *Also show canceled and replaced posts* for the history),
  *Problems* and *Results* (the real numbers of your posts).

## Controls and emergency stop

* **Start Autopilot** / **Pause Autopilot** (Autopilot → Overview): paused means queued work waits; jobs you start by
  hand still run.
* **Stop all jobs…** (Autopilot → Overview → *Pause or stop everything*): cancels queued work, asks running jobs to
  stop at their next safe point (including manual renders and uploads) and pauses everything until you press
  **Resume jobs** (in the *All jobs are stopped* banner). No new transfer starts while stopped. An upload that is
  already transferring stops at its next safe point; the platform may have accepted its final bytes already, so
  check the existing outcome if one was in flight.
* Per job: **Cancel…**, **Retry** and the job **Log** (Autopilot → Advanced → Jobs).
* Per found video: **Permission…**, and in its More menu **Clip now**, **Skip this video** and **Add the file…**
  (Autopilot → Permissions & sources → *Found videos and their permission*).
* On/off is on the Autopilot page; Settings → Defaults has the daily target (and the posting hours and topics),
  Settings → Accounts has automatic publishing; Settings → Advanced has every other target, limit and switch described
  above.

## Blocked or limited capabilities

These are not simulated; the UI shows them as unavailable or explains the restriction.

| Capability | Status |
| --- | --- |
| Google Trends data | Not available: the official Google Trends API is an application-gated alpha. Not scraped. |
| TikTok trends and TikTok discovery | Not available: TikTok offers no trend or search API for general developers. TikTok is never scraped. |
| YouTube momentum metrics (velocity, engagement rates, derived totals, learning from YouTube results) | Only with Google's approval under the additional policies for derived metrics; enable the setting only if your project was approved. |
| Broad YouTube trending | `chart=mostPopular` covers Music, Movies and Gaming only; general discovery uses topic searches within the 100-call search bucket. |
| Downloading YouTube or other platform videos | Explicit submitted links use guarded public extraction; other inputs retain existing download settings. No login/protection bypass is offered. The owner must have lawful access/use rights; original files or official creator downloads avoid unavailable-link problems. |
| Unattended YouTube publishing | New submitted inputs can use explicit Make & upload requests. Other posts need review or optional standing consent outside review mode. Deliberate holds and actual platform limits still apply. |
| Unattended TikTok publishing | Each post still needs your consent; packages/drafts need completion in TikTok. |
| Public from an unverified YouTube project | Current API permits it; check actual returned visibility and quota. |
| Public from a private TikTok profile | Everyone is unavailable; this app does not change your profile privacy. |
| 15 posts/day on both platforms | Subject to the YouTube quota (by default 100 upload calls a day, shared with anything else your Google Cloud project uploads), TikTok's per-creator posting limits and your own limits. |
| TikTok retention metrics | Not available from TikTok's API. |

## Legal pages (Terms of Service and Privacy Policy)

[`docs/legal/`](legal/) holds the public website: `index.html` (product page), `privacy.html`, `terms.html` and
`site.css`. The pages were written from an audit of the code (what is stored, what is sent where, how long it is kept,
disconnecting and deleting) and name the publisher, contact email and governing law. **No lawyer has reviewed them.**
`tests/test_autopilot_discovery.py` checks that the folder holds only these four files, with no placeholders, scripts,
forms or outside resources. When a change alters what ClipFoundry stores or sends, update the pages with it.

Where they are served:

* **In the app:** <http://127.0.0.1:8765/legal/>, `/legal/privacy` and `/legal/terms` (linked at the bottom of the
  sidebar). These are only reachable on your PC, so they are not enough for the developer consoles.
* **Public website (needed for the Google OAuth consent screen and the TikTok developer app):** GitHub Pages from a
  separate `gh-pages` branch that holds only the four files and an empty `.nojekyll`, so nothing else in the
  repository is published. The addresses are then `https://<user>.github.io/<repo>/`, `.../privacy.html` and
  `.../terms.html`; open them once before entering them in Google Cloud (OAuth consent screen → App information) and
  TikTok for Developers (app details). Publishing needs the owner's OK.
* **Keep the website addresses separate from the sign-in addresses.** The OAuth redirect addresses stay on your own
  PC (`http://127.0.0.1:8765/api/oauth/youtube/callback` and `.../api/oauth/tiktok/callback`, the TikTok one as
  Settings → Accounts shows it); the website is never a redirect address.

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

## Troubleshooting

In submitted mode, **Ready for a video link or file** means it is waiting for your input, not running a search.
Add a video in Missions, then inspect that video's progress/hold and Queue. Search-key failures do not block this
path. Failed download/access, missing GPU/model/disk, weak moments, final checks, paused publishing, account drift
and actual platform waits can still require action.

For optional discovery, if Autopilot ran overnight without making clips, first look at Autopilot → Overview: the line under the headline
(what it is doing, or why nothing is being clipped), *Next online search* (with the last search), any search that did
not work, **Needs you**, and **Activity**. Posting hours limit when posts go out; they do not prevent
discovery or clipping overnight. A connected account alone does not supply downloadable original files. Discovery
also checks your connected YouTube channel, channels covered by active recorded permissions, and shared folders in
creator agreements. These still pass the same channel, rights, file-access and final-quality checks.

| Problem | What to do |
| --- | --- |
| "Connect YouTube to start finding content." (Autopilot → Activity) | No way to find videos is on: the free-license library is off, YouTube is not connected and no folder is watched. Connect YouTube, turn the library back on (Settings → Advanced → Discovery and rights), or add a folder or a creator agreement with a shared folder under Autopilot → Permissions & sources. |
| "Autopilot's background work has stopped" (Needs you; *Background work has stopped* on Overview) | The app answers, but its workers have not for over a minute and could not be restarted. Close the black ClipFoundry window and start ClipFoundry again with `start.bat`. If it happens again, see Autopilot → Advanced → System and `data/logs/workers.log`. |
| "No usable video files yet" (Overview) | Videos it may use were found, but there is no file it is allowed to get (YouTube does not let apps download videos, even your own). Put the original in your videos folder, use a creator's shared folder, or **Add the file** in Activity. |
| "No covered videos found yet" (Overview) | The videos found so far belong to other people and no agreement or license covers them. Put your own videos in your videos folder, or record an agreement you really have. |
| "Waiting for the next search" (Overview) | The last online search finished; *Next online search* shows when the next one is. Your videos folder and waiting files are checked every 3 minutes meanwhile. |
| "Some searches did not work" (Overview, with the search and what to do) | Follow its fix. The other searches keep working and what was already found is kept. A platform's wait (Retry-After) is never shortened. |
| "No strong opportunities yet. ClipFoundry is still looking." | Discovery works, but nothing found so far is strong enough. It keeps looking; nothing to do. |
| Workers show *Not running* (Autopilot → Advanced → System) | Check Needs you. If the worker process cannot start, switch Settings → Advanced → Autopilot details → *Worker process* to *Inside the app*. |
| Nothing gets clipped | Check Activity: it says for each video why it was skipped (not covered, no allowed way to get the file, too short, a repeat) or where it stopped. Unknown rights are skipped without questions by default. Your own recordings are clipped without questions when you add them as your own content (your videos folder, or *Add…* → *A video, link or folder of yours…* under Autopilot → Permissions & sources). |
| Jobs wait for the GPU | Another heavy GPU job (or another program) is using it; see the *GPU* panel (Autopilot → Advanced → System). Lower *Free GPU memory needed* (Settings → Advanced → Transcription and GPU) only if you know the model fits. |
| "Ran on the CPU instead of the GPU" in the *GPU* panel (or *CPU (slower) for the last video* on Autopilot → Overview) | Run `gpu-check.bat` and follow the fix it prints (see INSTALL.md). |
| "GPU transcription is not working" (Needs you), or "Autopilot transcription is paused: the GPU could not be used" (Autopilot → Advanced → System) | Run `gpu-check.bat` and follow the fix it prints. Until it is fixed, you can turn on *Allow CPU transcription in Autopilot* in Settings → Advanced → Transcription and GPU. |
| Discovery stopped: quota ("YouTube's daily limit for searches is used up" on Overview) | The YouTube quota share for discovery is used up; it resumes after midnight Pacific. Publishing keeps its reserve. |
| Posts wait in *Needs review* (*Needs your OK*) | Open each one in Posts and approve it (**Approve for YouTube** / **Approve for TikTok**). YouTube can instead use the automatic-publishing permission you turned on; TikTok always needs your OK on each post. |
| YouTube reports Private for a requested Public upload | Check its returned restrictions and YouTube Studio. |
| TikTok: privacy options disabled | Your TikTok app is not audited; only *Only me* is possible, or use *Send to TikTok inbox*. |
| Something is running that should not | **Stop all jobs…** (Autopilot → Overview), then look at Autopilot → Advanced → Jobs and the job logs. |
| After an update | Close the old console window, start again, reload the page (Ctrl+F5). |

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
