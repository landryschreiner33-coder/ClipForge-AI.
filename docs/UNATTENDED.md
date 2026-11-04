# Running ClipFoundry unattended

ClipFoundry can turn a recorded-video link/file you submit into quality-checked clips and automatically upload
qualifying clips to YouTube. **Missions → Make & upload clips** asks once for that input's connected account,
confirmed audience, kids answer and reuse basis. Relevant supported Brain guidance uses Settings fallback.
**Make clips only** keeps results local. No automatic searching or watched-folder intake runs in the default
submitted mode, and no search key is required. Older Queue backlog still waits for manual review by default;
TikTok always keeps individual review. An input request does not approve other inputs or grant source ownership.
This is a local PC app: the PC must remain powered on, connected to the internet and able to use its GPU and disk.
It cannot promise uninterrupted operation, make a sleeping/offline PC run, or override platform/account restrictions.

## Start the watchdog

1. Finish the normal setup and a real GPU check using `gpu-check.bat`.
2. Connect YouTube and confirm who watches. Submit your video in Missions with **Make & upload clips**; check its
   actual progress/holds before relying on unattended work. Keep any deliberate posting limits/window.
3. Close the ordinary ClipFoundry window, then double-click `run-unattended.bat`.
4. Open `http://127.0.0.1:8765` to check progress. Keep the unattended window open; Ctrl+C stops it and its workers.

The launcher reuses `start.bat --setup-only`, including the existing virtual environment and GPU setup. It does not
modify normal `start.bat` behavior. The Python watchdog restarts the main app after an unexpected process exit,
waiting 2, 4, 8, 16, 32, then at most 60 seconds between repeated failures. After five minutes of continuous app
operation, the restart delay resets to two seconds. It does not reopen a browser on each restart. It does not
automatically unpause Autopilot or publishing, change audience choices, grant consent or retry ambiguous uploads.
It detects process exit; it does not detect a still-running, hung main app.

`data/logs/unattended.log` captures app output and watchdog transitions. It rotates at approximately 5 MiB and keeps
two older copies (approximately 15 MiB total). Existing worker logs remain separate. A profile lock and a port lock
prevent duplicate unattended instances; an occupied port stops the watchdog rather than starting a second server.
The watchdog owns the app's process tree: explicit stop and restart cleanup include its workers and media children.
Windows uses a kill-on-close Job Object; other platforms use a dedicated process group. No app work starts until
the watchdog has established this ownership. Don't run normal `start.bat` against the same data folder at the same
time, even on a different port.

For an isolated profile, select the same data path and port for every subsequent launch:

```bat
set "CLIPFOUNDRY_DATA=C:\CF14\data\pr14-test"
set "CLIPFOUNDRY_PORT=8899"
call C:\CF14\run-unattended.bat
```

Keep existing OAuth data under the same Windows user: its credentials are protected with that user's DPAPI keys.
Using an empty profile means reconnecting accounts and configuring Autopilot there; profiles do not share settings.

## Start when you log into Windows

These are optional Task Scheduler instructions; ClipFoundry does not create a task or change Windows settings.
First run `run-unattended.bat` manually and confirm setup, GPU mode and the intended data profile work.

1. Open Task Scheduler and choose **Create Task**. Name it `ClipFoundry unattended`.
2. Under **General**, select your usual Windows user and **Run only when user is logged on**. Use the same user
   that connected the accounts; do not use SYSTEM or another service account. Administrator privileges are not
   required for normal local operation.
3. Under **Triggers**, add **At log on** for that specific user, with an optional 30-second delay.
4. Under **Actions**, choose **Start a program**. Set the program to
   `C:\Windows\System32\cmd.exe`, arguments to `/c "C:\CF14\run-unattended.bat"`, and **Start in** to `C:\CF14`.
   Replace these paths with the actual short installation folder. For a custom data profile, schedule your own
   small `.bat` wrapper containing the environment variables above and an absolute `call` to the launcher.
5. Under **Settings**, clear **Stop the task if it runs longer than**. Set **If the task is already running** to
   **Do not start a new instance**. Optionally enable restart on failure every minute, with three attempts, for
   the watchdog itself. Disable or end the task before intentionally stopping or upgrading the scheduled app.
6. Under **Conditions**, choose AC/battery behavior deliberately. A laptop can stop or refuse to start the task
   on battery if those boxes are enabled. Avoid letting the PC sleep while you expect work to continue.

This starts after that user logs in, not before login. Logging out, rebooting or powering down ends the session;
the next login starts a new one. ClipFoundry's existing **Keep the PC awake** setting requests wakefulness while
Autopilot is active on Windows, and reports failures. It cannot prevent forced sleep, lid actions, power loss,
restarts or network failures. A locked screen is different from logging out.

## What still needs attention

For a submitted video, first check **Missions → Submitted videos** for ready/waiting/uploading/uploaded counts
and a hold reason. **Ready for a video link or file** means the app is waiting for your input. **Cancel video**
stops its future work without deleting completed media or already published posts. Missing/changed source bytes,
account/audience/terms changes, final checks and Pause publishing can hold an automatic request. The request does
not clear emergency Stop or grant any old backlog upload permission.

For optional discovery or older backlog, open **Missions → Why clips are waiting to post**. This panel
reports post-text preparation, final checks, local-only coverage and actual scheduled counts for connected
platforms. It explains unconfirmed audiences, disabled scheduling/publishing, pending owner review, and, when
review mode is explicitly off, missing or outdated YouTube
permission, zero limits and approved posts without a confirmed new time. Routine retries do not require an
approval; failed/canceled post preparation remains visible in Jobs. Interrupted eligible finished outputs resume
their post preparation automatically, without re-rendering the whole batch or reviving canceled work.

With only YouTube connected, TikTok is optional. In Setup or **Settings → Integrations → Who watches**, choose
and confirm the intended YouTube audience. For older/optional discovery posts, leave **Prepare & schedule for
review** on, then open **Queue → Needs review** to inspect each exact clip and confirm any unrecorded reuse permission with its basis before approval.
YouTube also needs the post's made-for-kids answer. The approved post uploads at its time; approving a past-due
post allows prompt publishing. If you deliberately turn review mode off, **Missions → How posts go out → Turn on
automatic publishing** provides the separate channel/audience-bound permission for covered clips.
Existing Private posts keep their original visibility and applicable permission. A new Public choice does not
turn those older posts public. Uncovered clips remain local review drafts until you record a valid individual
reuse confirmation and approve their exact post. A draft's posting time grants no upload permission.

Public posting requires an explicit supported audience choice, the correct connected account, reuse permission,
passing final-file checks and the appropriate exact-post approval, input-scoped request or optional standing
YouTube permission. Previous private schedules stay private. The app reports actual returned visibility and restrictions. An External Google OAuth app left in
Testing usually gives YouTube refresh-token grants a seven-day lifetime; move that OAuth app to Production and
reconnect the channel for long-running access. Production is not a guarantee against later token revocation,
account restrictions or quota exhaustion. Check the Google Console requirements for your app's requested scopes.
TikTok still requires supported creator options and approval for each post; a draft/manual package needs you to
finish publishing in TikTok. A private TikTok profile cannot be made publicly viewable by this watchdog.

Quota exhaustion, expired/revoked authorization, unavailable source access, GPU faults and ambiguous upload
outcomes can pause work or require action. These holds are intentional; restarting does not bypass them. Check
Activity and account status periodically, maintain free disk space, and test a short real upload and an overnight
run on your Windows PC before relying on unattended publishing. Cloud tests cannot verify your PC, RTX 3050,
power settings, real accounts or a Windows Task Scheduler session.
