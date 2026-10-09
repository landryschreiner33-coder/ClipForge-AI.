# Test PR #14 in a separate Windows folder

This branch is a review build. PR #14 remains unmerged. Use the exact-commit ZIP linked in the PR handoff.

1. Close your normal ClipFoundry console. Back up its entire `data` folder somewhere separate while it is closed.
   Keep the original installation and its `.venv` untouched.
2. Download the ZIP and use **Extract All**. Open the generated folder containing `test-isolated.bat`, then copy
   **that folder's contents** into a new short folder, **`C:\CF14`**. Check that **`C:\CF14\test-isolated.bat`** and
   `C:\CF14\requirements.txt` exist directly there. Avoid putting the long generated archive folder inside another
   copy of the same folder: dependency filenames can exceed Windows' path limit. Do not extract over your usual
   installation or copy its `data` or `.venv` into this test copy.
3. Double-click **`test-isolated.bat`** in the extracted folder. It performs the usual setup using this copy’s own
   `.venv`, then opens **http://127.0.0.1:8899**. Leave its console open. Test data and videos live under
   `data\pr14-test`; the launcher overrides inherited data, video and port settings.
4. Use a **copy of one of your own videos**. Check local transcription, clip selection, captions, rendering,
   playback and export. Keep real posting accounts disconnected for this first check.
5. On Office, verify all 25 names are readable at your normal Windows scaling. Select robots to inspect their
   task, dependencies and next robot. Try Follow system, Full and Reduced; Full should animate even with Windows
   animation effects turned off. Pause/Stop should show the corresponding real state.
6. On Brain, upload a TXT/MD/CSV/JSON/DOCX guide, choose a supported preference, save and approve it. **Try a
   decision** previews the preference lookup. Process another matching video to see a recorded influence in
   **Brain → Decisions**. Editing needs new approval; disable/delete should stop future use. Good/bad MP4/MOV/WebM
   examples are separate teaching references, never posting results.
7. Run the **isolated GPU command below** from this test folder while the normal app is closed. It does not publish.
   This checks CUDA transcription only. Separately render a clip in the test app, check its saved render information
   for `h264_nvenc`, and look and listen for caption timing and sync. GPU runtime, Windows setup, fonts and scaling
   were not verified in the Linux test machine.
8. Close the test console to stop it. Your original installation and data remain separate; reopening the original
   `start.bat` resumes that copy. Do not point the old build at a database opened by the new build.

For later account testing, first review [PLATFORM_CAPABILITIES.md](PLATFORM_CAPABILITIES.md). Connecting an account
alone does not authorize automation. New Public YouTube uploads need Public audience confirmation, an audited
project and fresh channel-bound automatic-publishing permission. Review limits and the posting window before
turning it on. Existing Private schedules stay Private. TikTok still requires per-post choices and consent; if its
app approval is unavailable, use the manual package or an approved inbox draft. No real videos were posted during
development.

If setup already failed with `No such file or directory` for a long `anthropic\types\beta\...` filename and a
Windows long-path hint, close that failed console and repeat step 2 with **fresh ZIP contents** in `C:\CF14`.
Do not move the partially installed `.venv`: Python environments contain paths to their original location.
The launcher creates a new environment in the short folder. Your normal app and its data should remain untouched;
no administrator setting or registry edit is needed for this short-folder workaround. If `C:\CF14` is unavailable,
use another short writable folder, such as `C:\Users\landr\CF14`, with the launcher directly inside it.

For the GPU check, open PowerShell in the extracted test folder and run:

```powershell
$env:CLIPFOUNDRY_DATA = Join-Path (Get-Location) 'data\pr14-test'
$env:CLIPFOUNDRY_VIDEOS = Join-Path (Get-Location) 'data\pr14-test\videos'
.\gpu-check.bat
```

Keep these explicit paths: the isolated launcher's settings apply only inside its console. They do not carry into
a separately opened GPU-check console. The command above overrides any inherited path to the normal database.

For a timing report after your real local checks, open `http://127.0.0.1:8899/api/office/performance?days=7` or run
this in PowerShell from the test folder:

```powershell
$env:CLIPFOUNDRY_DATA = Join-Path (Get-Location) 'data\pr14-test'
.\.venv\Scripts\python.exe -m clipfoundry performance --days 7
```

The report excludes waits and incomplete stages. Use it with your GPU check when considering a server; see
[PERFORMANCE.md](PERFORMANCE.md).
