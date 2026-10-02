# Installing ClipFoundry (Windows)

ClipFoundry is a local app: a small Python server plus a web UI that opens in your browser. Nothing is uploaded
anywhere.

## Requirements

| | Minimum | Recommended |
| --- | --- | --- |
| OS | Windows 10/11 (64-bit) | Windows 11 |
| Python | 3.10 | 3.11 or 3.12 |
| FFmpeg | any recent build with libx264 + libass | `winget install Gyan.FFmpeg` |
| RAM | 8 GB | 16 GB |
| GPU | not required | NVIDIA RTX (recent driver) for fast transcription and NVENC encoding |
| Disk | ~3 GB (dependencies + Whisper model); ~6 GB with an NVIDIA GPU (CUDA libraries + the larger model) | plus space for your videos |

Node.js is **not** required. The UI ships prebuilt in `frontend/dist`.

## 1. Install Python

Download Python 3.11 or 3.12 from <https://www.python.org/downloads/windows/>. In the installer, tick
**"Add python.exe to PATH"**.

## 2. Install FFmpeg

Open *PowerShell* and run:

```powershell
winget install Gyan.FFmpeg
```

Close and reopen the terminal afterwards so `ffmpeg` is on your PATH. Alternatively, download a full build
(for example from gyan.dev or BtbN), unzip it, and place it so that `tools\ffmpeg\bin\ffmpeg.exe` exists inside the
ClipFoundry folder. You can also point to it in **Settings → Advanced → Rendering, AI scoring and system → FFmpeg
location**.

## 3. Start ClipFoundry

Double-click **`start.bat`**. On the first run it:

1. creates a private Python environment in `.venv`,
2. installs the dependencies from `requirements.txt` (a few minutes),
3. if an NVIDIA GPU is present, installs the CUDA libraries for GPU transcription (see below),
4. prints `Transcription: GPU mode` or `CPU mode`, then starts the server and opens <http://127.0.0.1:8765> in your
   browser.

Later runs start in seconds. Keep the console window open while you use the app; close it (or press Ctrl+C) to quit.

Options: `start.bat --port 9000` uses a different port. `start.bat --host 0.0.0.0` exposes the app on your local
network (only do this on a trusted network, since there is no login).

## 4. First video

The first transcription downloads the Whisper model into `data\models` (about 500 MB for `small`, 1.6 GB for
`large-v3-turbo`). After that ClipFoundry works fully offline.

Each model goes into its own short folder, e.g. `data\models\large-v3-turbo`. Before Whisper loads it, ClipFoundry
checks that every file is there (`config.json`, `model.bin`, `preprocessor_config.json`, `tokenizer.json`,
`vocabulary.json`) against the sizes and checksums published on Hugging Face. A download that was interrupted or is
damaged is repaired automatically: only the bad files are downloaded again. Models left in the old
`models--…\snapshots\…` layout by earlier versions are moved into the new folder instead of downloaded again.

Which model is used automatically:

* NVIDIA GPU detected → `large-v3-turbo` (float16) on the GPU
* CPU only → `small` (int8). For a faster but less accurate run pick `base` as the *Whisper model* in Settings →
  Advanced → Transcription and GPU; for better accuracy pick `medium`.

Rough speed for a 60-minute video: GPU ~2-4 min to transcribe; CPU (8 cores, `small`) ~10-20 min. Rendering takes
about 15-40 s per clip on CPU, faster with NVENC.

## NVIDIA GPU acceleration

* **Transcription on the GPU is automatic.** When `start.bat` finds an NVIDIA GPU (via `nvidia-smi`), it installs the
  CUDA 12 cuBLAS and cuDNN 9 libraries from `requirements-gpu.txt` once (about 1 GB). faster-whisper needs exactly these
  versions, whichever CUDA Toolkit you have installed, so a CUDA 13 toolkit alone is not enough. ClipFoundry makes these
  DLLs visible to CTranslate2 when it starts.
* On an RTX card like the RTX 3050 6 GB, transcription uses `device="cuda"` with `compute_type="float16"` and the
  `large-v3-turbo` model. float16 runs on the Tensor Cores and fits easily in 6 GB. `int8_float16` needs about 40%
  less GPU memory at similar speed with a small accuracy cost. ClipFoundry switches to it on its own on GPUs with
  under 5 GB, or if the GPU runs out of memory. You can also choose it in Settings → Advanced → Transcription and GPU
  (*Compute type*).
* When it starts, the console says which mode it is in:

  ```
  Transcription: GPU mode - NVIDIA GeForce RTX 3050, 6 GB (CUDA)
                 faster-whisper large-v3-turbo, compute type float16
  ```

  Whenever CTranslate2 reports a CUDA device, ClipFoundry uses GPU mode. If a CUDA library looks missing, it adds a
  warning and the fix, but still tries the GPU first. It says `CPU mode` only when there is no usable CUDA device, or
  when Settings → Advanced → Transcription and GPU → *Device* is set to *CPU*. Autopilot → Advanced → System (the
  *This computer* and *GPU* panels) shows the same information.
  After updating ClipFoundry, close the old console window and run `start.bat` again, then reload the page
  (Ctrl+F5). An old window keeps running the old version.
* Each transcription logs the device and compute type it actually used (`Transcription starting: device=cuda
  compute_type=float16 model=large-v3-turbo`), plus its speed when it finishes. If the GPU fails partway through, the
  job continues on the CPU (`int8`). The console, the source video page and Autopilot → Advanced → System (the *GPU*
  panel) all show a warning with the reason, so a fallback is never silent.
* **Video encoding (NVENC)** is used automatically when your FFmpeg build and driver support it (Settings → Advanced
  → Rendering, AI scoring and system → *Video encoder*).

### Checking that the GPU is really used

Drag a video onto **`gpu-check.bat`** in the ClipFoundry folder. You can also double-click it for a quick
synthetic test, or run `gpu-check.bat "C:\path\to\video.mp4" --seconds 120` from a terminal.

* It first runs the same setup as `start.bat` (the `.venv` environment, dependencies and CUDA libraries), then runs
  `.venv\Scripts\python.exe -m clipfoundry gpu-check`. It uses exactly the environment the app uses, not a system
  Python.
* It uses the app's own transcription settings (model, compute type, beam size, language) and explicitly requests
  `device="cuda"` with the app's GPU compute type (`float16` on an RTX 3050). It never falls back to the CPU.
* Step 1 creates the Whisper model and checks that CTranslate2 reports it on `cuda`. Step 2 transcribes the first
  5 minutes through the same code as the app. It prints the speed, CPU usage, and GPU utilization and memory
  sampled with `nvidia-smi`.
* It prints `PASS` only when the model initialized on CUDA and the transcription finished on the GPU. Otherwise it
  prints `FAIL` with the exact CTranslate2 error and the fix. The window stays open until you press a key.

If `gpu-check.bat` is missing, or it says the folder is out of date, update the whole ClipFoundry folder (`git pull`,
or download the branch ZIP again and copy it over the folder). Copying only the `.bat` file is not enough, because
the check also needs the newer app files. Your `data` and `.venv` folders are kept.

In **Windows Task Manager** (Performance → GPU), CUDA work does **not** appear on the default "3D" graph. Click the
title of one of the small graphs and choose **Cuda** (or **Compute_0**) to see it. `nvidia-smi -l 1` in a terminal
shows it too.

## Optional: smarter clip scoring with a local LLM (free)

The built-in heuristic works offline and needs nothing else. For LLM-assisted scoring and hook writing:

* **Ollama**: install from <https://ollama.com>, run `ollama pull llama3.1:8b` (or `qwen2.5:7b`), then in
  **Settings → Advanced → Rendering, AI scoring and system → AI scoring** choose *Ollama (local AI, free)*, press
  *Save settings* and click *Test connection*.
* **LM Studio**: load a model, start the local server (default `http://localhost:1234/v1`), choose
  *LM Studio or another OpenAI-compatible local server*, and enter the model name (*Server model*).

Only the 8-12 strongest candidate clips are sent to the model, never the full transcript.

## Optional: Claude API (paid)

Choose *Claude API (optional, paid)* under Settings → Advanced → Rendering, AI scoring and system → *AI scoring* and
paste an API key (*Claude API key*). This costs money per call. Use *Max candidates* to cap how many clips per video
are sent. The key is stored only in your local `data\clipfoundry.db`.

## Optional: publishing to YouTube Shorts

ClipFoundry uploads through the official **YouTube Data API v3** with your own free Google Cloud project. You sign in on
Google's page; ClipFoundry never sees or stores your Google password. It receives OAuth tokens, which are stored
encrypted with Windows DPAPI (only your Windows account on this PC can read them).

1. Open <https://console.cloud.google.com> and create a project.
2. **APIs & Services → Library**: enable **YouTube Data API v3**. Optional: enable **YouTube Analytics API** too, so
   ClipFoundry can show the real watch time and retention of your uploads.
3. **OAuth consent screen**: choose *External*, enter an app name and your e-mail, and add your own Google account
   under *Test users*.
4. **Credentials → Create credentials → OAuth client ID**, application type **Desktop app**. Copy the client ID and
   secret into **Settings → Accounts → YouTube → Your YouTube app codes** (*OAuth client ID* and *Client secret*), or
   into the dialog that **Connect YouTube…** opens in the first-time setup or on the Autopilot page.
5. Click **Connect YouTube** (it saves the codes first), sign in and allow access. The connected channel's name appears
   in Settings → Accounts.

Things Google enforces, which ClipFoundry explains on screen:

* **Unaudited projects upload Private only.** Google locks every video uploaded by an API project that has not passed
  the [YouTube API audit](https://support.google.com/youtube/contact/yt_api_form) to Private, even if you choose Public
  or Unlisted. Private uploads work for testing. After the audit, tick *My Google Cloud project passed YouTube's API
  audit* in Settings → Accounts → YouTube → Your YouTube app codes.
* **Testing-mode connections expire after 7 days.** While the consent screen is in *Testing*, connect again weekly
  (**Reconnect YouTube** in Settings → Accounts once the sign-in has expired), or set it to *In production* (for your
  own use you can continue past the "unverified app" screen).
* **Quota.** Uploads count against your project's daily YouTube API quota. If it runs out, ClipFoundry says so; try
  again the next day (quotas reset at midnight Pacific Time).
* Vertical videos of up to 3 minutes are classified as Shorts by YouTube automatically.
* YouTube requires you to say whether a video is *made for kids*; Prepare post and each post's review page ask every
  time.

## Optional: publishing to TikTok

ClipFoundry uses TikTok's official **Content Posting API** and **Login Kit for Desktop** with your own free TikTok
developer app. You sign in on TikTok's page; ClipFoundry never sees or stores your TikTok password.

1. Sign in at <https://developers.tiktok.com> and create an app.
2. Add the products **Login Kit** (platform *Desktop*) and **Content Posting API** (turn on *Direct Post* if you want
   to post directly).
3. Add the scopes `user.info.basic`, `video.upload`, `video.publish` (Direct Post) and `video.list` (statistics). You
   can switch off Direct Post or statistics in Settings → Accounts → TikTok → Your TikTok app codes (*Permissions to
   ask TikTok for*) if your app does not have them.
4. Register the redirect URI shown in **Settings → Accounts → TikTok → Your TikTok app codes** (*Redirect address to
   register in your TikTok app*, with a *Copy* button; for example `http://127.0.0.1:8765/api/oauth/tiktok/callback`;
   use your port if you changed it).
5. While the app is not reviewed, add your TikTok account as a target user. Paste the client key and secret there
   (*Client key* and *Client secret*) and click **Connect TikTok** (it saves them first).

Two official ways to post, both on Prepare post and on each TikTok post's review page:

* **Post directly** (Direct Post): posted to your profile with the privacy you choose from the options TikTok offers
  for your account. Until TikTok audits your app, TikTok only accepts Direct Posts when your account is private,
  limits them to "Only me", and allows at most 5 users per day. ClipFoundry explains this and blocks settings TikTok
  would reject.
* **Send to TikTok inbox** (draft): works without the audit. The video arrives in the TikTok app as a draft; tap the
  notification, edit if you like, choose who can see it and post it.
* Or use **Export** and upload the MP4 on <https://www.tiktok.com/tiktokstudio/upload> yourself.

As TikTok's sharing guidelines require, ClipFoundry shows your TikTok nickname, never pre-selects a privacy option,
leaves comments, duets and stitches off unless you allow them (and greys them out if your account disables them),
offers the commercial content disclosure, and shows TikTok's Music Usage Confirmation before posting. It does not
scrape TikTok or automate its website.

Connecting and publishing only work in the browser on the PC that runs ClipFoundry (`http://127.0.0.1:8765`), even
if you started it with `--host 0.0.0.0`.

## Performance statistics

After publishing, **Refresh numbers** (under Posts → Results for every post, or under *Real numbers* of one upload on
its post page or on Prepare post) reads the real numbers of your own uploads from the official APIs:

| | Views | Likes | Comments | Shares | Watch time / retention |
| --- | --- | --- | --- | --- | --- |
| YouTube | Data API | Data API | Data API | Analytics API | Analytics API (enable *YouTube Analytics API*; data arrives 2-3 days after upload) |
| TikTok | `video.query` | `video.query` | `video.query` | `video.query` | not available from TikTok's API |

TikTok only reports public posts. For an inbox draft you finished in the TikTok app, paste the post's link under the
upload on Prepare post (*Posted it in the TikTok app?*), or use **Link the post…** on a planned post's page, to track
it. Anything a platform does not report is shown as "—" with the reason; ClipFoundry never estimates it. Every
refresh is kept as a snapshot, and **Download data (CSV)** under Posts → Results downloads each clip's scores at
publish time next to its real results.

## Optional: Autopilot

Autopilot is off until you turn it on. The full guide, including what the platforms allow, is in
[docs/AUTOPILOT.md](docs/AUTOPILOT.md). The short version: press **Get started** on Home (or **Set up Autopilot** on
the Autopilot page) and follow the three steps of the setup.

1. **Add your videos**: **Open videos folder** and put videos you made in it (or **Choose a video** to start with one).
2. **Choose how to work**: *Let Autopilot do it*, and keep or change the suggested topics.
3. **Set up posting**: **Connect YouTube** (the first time, paste your Google app's client ID and secret; see above),
   **Connect TikTok** (optional), then **Start Autopilot**.

Autopilot then finds trending videos by itself; you do not add sources, feeds or rules. It asks you (under
**Needs you**) only when it must: whether you have permission to use a strong video, for the original file of a
YouTube-hosted video you said yes to, and to approve posts (both platforms require your approval of each post;
approved posts are published at their time). Your own videos can be added any time: put them in your videos folder,
or use *Add…* under Autopilot → Permissions & sources. Everything technical is on the Autopilot page (sources and
permission rules under **Permissions & sources**; jobs, quota and workers under **Advanced**) and in Settings →
Advanced, for example a YouTube Data API key or your project's raised daily quota (both in Settings → Advanced →
Discovery and rights).

The workers run in a separate background process that starts and stops with the app. **Stop all jobs…** on the
Autopilot page (under *Pause or stop everything*) halts everything until you press **Resume jobs**. GPU transcription
is unchanged: Autopilot uses the same CUDA path and runs one heavy GPU job at a time.

For the Google OAuth consent screen (production) and the TikTok developer app you need public **Terms of Service** and
**Privacy Policy** URLs. The pages are in `docs\legal` (no lawyer has reviewed them) and are published with GitHub
Pages (see [docs/AUTOPILOT.md](docs/AUTOPILOT.md#legal-pages-terms-of-service-and-privacy-policy)).

## Where things are stored

Everything lives in the `data` folder next to the app (override it with the `CLIPFOUNDRY_DATA` environment variable):

```
data\clipfoundry.db            projects, clips, metadata, settings, publishing history (tokens are encrypted),
                               Autopilot jobs, sources, rights, schedule and learning data
data\projects\<id>\            source video, transcript, candidates, rendered clips, exports
data\models\<model>\           downloaded Whisper models, one verified folder each (e.g. large-v3-turbo)
```

To back up, copy the `data` folder. Deleting a video in the Library (*Delete video and clips…*) removes its folder.

## Updating

**Don't delete the ClipFoundry folder to update.** Unless you set `CLIPFOUNDRY_DATA`, the `data` folder inside it holds
your database (settings, schedule, approvals, account connections), your projects and clips, and the downloaded
Whisper models; the `.venv` folder holds Python and the GPU (CUDA) libraries; `tools\ffmpeg` holds FFmpeg if you put
it there. Deleting the folder deletes all of that. (Your videos folder, `Videos\ClipFoundry` in your user folder, is
outside the ClipFoundry folder, so the videos you put there are safe either way.)

With `git`: close ClipFoundry, run `git pull` in the folder, start `start.bat`. `data`, `.venv` and `tools\ffmpeg` are
never touched by git.

With the ZIP (https://github.com/landryschreiner33-coder/ClipForge-AI./archive/refs/heads/claude/wonderful-ritchie-909tq3.zip):

1. Close ClipFoundry (close the `start.bat` window).
2. Check where your data is: the top of the Settings page names ClipFoundry's data folder (also Settings → Advanced →
   Rendering, AI scoring and system → System → *Data folder*). If it is outside the ClipFoundry folder (you set
   `CLIPFOUNDRY_DATA`), only steps 4-5 and 7 apply.
3. Back up: copy the `data` folder somewhere else (at least `data\clipfoundry.db`).
4. Rename the old folder, e.g. `ClipFoundry` → `ClipFoundry-old`.
5. Unzip the download and rename the unzipped folder to the old name (`ClipFoundry`), in the same place, so the path is
   exactly the same as before.
6. Move `data`, `.venv` and `tools` (if they exist) from `ClipFoundry-old` into the new `ClipFoundry` folder. Keeping
   `.venv` at the same path keeps your working CUDA setup; nothing is downloaded again.
7. Start `start.bat`. It reinstalls packages only when `requirements.txt` or `requirements-gpu.txt` changed. Check that
   your videos are in the Library and your accounts are still connected (Settings → Accounts), then delete
   `ClipFoundry-old`.

Account connections are encrypted for your Windows user on this PC, so they keep working only in the same Windows
account; the database copy is otherwise complete.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| "FFmpeg was not found" | `winget install Gyan.FFmpeg`, then reopen the terminal; or set Settings → Advanced → Rendering, AI scoring and system → *FFmpeg location*. |
| Captions missing or wrong font | Use a full FFmpeg build (it needs `libass`). Gyan's builds include it. |
| Console says `CPU mode` although you have an NVIDIA GPU | Read the `Reason:` line. Usually run `start.bat` again (it installs the GPU libraries), or `.venv\Scripts\python -m pip install -r requirements-gpu.txt`. Also check Settings → Advanced → Transcription and GPU → *Device* is *Auto*. |
| `cublas64_12.dll` / `cudnn` errors | Same as above. A CUDA 13 toolkit does not provide these CUDA 12 files. Meanwhile ClipFoundry falls back to CPU and shows a warning. |
| "NVIDIA GPU was found by the driver, but CUDA is not usable" | Install the latest NVIDIA driver. |
| Task Manager shows 0% GPU during transcription | Switch a GPU graph from "3D" to "Cuda"/"Compute_0", or run `gpu-check.bat`. |
| `WinError 3` or a missing `preprocessor_config.json` while loading Whisper | Fixed in this version: models now use short folders and are verified and repaired automatically before loading. Run `gpu-check.bat` to see the model check. |
| Out of memory on GPU | Settings → Advanced → Transcription and GPU: *Whisper model* `small` or `medium`, or *Compute type* `int8_float16`. |
| Port 8765 already in use | `start.bat --port 8877` |
| Nothing happens after upload | Check the console window for errors. Only one job runs at a time; others wait in the queue. |
| Re-running the setup | Delete the `.venv` folder and run `start.bat` again. |
| Autopilot problems | See the troubleshooting table in [docs/AUTOPILOT.md](docs/AUTOPILOT.md#troubleshooting). |

## Linux / macOS

`./start.sh` does the same as `start.bat` (install `ffmpeg` with your package manager first). GPU transcription on
Linux uses the same `requirements-gpu.txt`.
