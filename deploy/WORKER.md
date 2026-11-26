# Running a ClipForge worker (Full Cloud)

A worker is ClipForge on a computer you rent (any Linux server or GPU machine you control). With **Settings →
Processing → Full Cloud** on your desktop, Make clips runs there: the desktop uploads the video (or sends the link),
the worker gets it, transcribes it, finds the moments, frames them, writes the captions and renders the clips, and
the desktop brings the finished clips back into the project. Nothing is posted from the worker. Design and limits:
[docs/clipforge/FULL_CLOUD.md](../docs/clipforge/FULL_CLOUD.md).

Status: tested with a real worker process on the same machine (tests/test_full_cloud.py, the private test job).
It has not been run on a rented server yet.

## What the worker does and does not do

- It answers **only** `/api/worker/v1/...` (with its key) and `/healthz`. Every other address, including the app's
  pages and its whole API, is 404, so the worker exposes nothing else when it is on the internet.
- It never posts, schedules, runs Autopilot, listens for phones or fetches the editing apps (these are off on a
  worker without any setting).
- A job's files stay on the worker until your desktop has brought the clips back (then they are deleted), or for
  72 hours after the job ended, whichever comes first.
- Your desktop sends the video, a transcript file when the project has one, and the clip choices from Settings
  (length, count, captions, framing, sound). It never sends accounts, keys, posts or your Brain.

## Set up (on the server)

1. Install Python 3.12 and FFmpeg, copy the repository, then
   `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
   For fast transcription on an NVIDIA GPU, also `pip install -r requirements-gpu.txt`; on a CPU-only
   server set the transcription device to CPU deliberately (below).
2. Make a key (keep it like a password, never in chat or git): `openssl rand -base64 32`.
3. Start the worker bound to this computer only, with the key in its environment:

   ```sh
   CLIPFOUNDRY_WORKER_KEY='<the key>' CLIPFOUNDRY_DATA=/var/lib/clipforge-worker \
   CLIPFOUNDRY_WORKERS=off .venv/bin/python -m clipfoundry --host 127.0.0.1 --port 8765
   ```

   For a service, put `CLIPFOUNDRY_WORKER_KEY=...` in an environment file readable only by the service's user
   (as `deploy/clipforge.service` does with `/etc/clipforge/clipforge.env`).
4. Put HTTPS in front of it. With Caddy (it gets the certificate itself):

   ```
   worker.example.com {
       request_body {
           max_size 20GB   # one video upload is one request; match CLIPFOUNDRY_WORKER_MAX_GB (default 20)
       }
       reverse_proxy 127.0.0.1:8765 {
           flush_interval -1
       }
   }
   ```

   The desktop refuses an `http://` address unless it is this computer, so the key and your videos never cross the
   internet unencrypted.
5. Optional: transcription settings on the worker itself (model, device) are the worker's own: start it once
   without the key on a private port, change Settings → Advanced, stop it, and start it again with the key.

## Connect the desktop

Settings → Processing: enter the worker's address (`https://worker.example.com`) and the key, then **Check**.
Set what an hour of the worker costs you (your provider's price; ClipForge cannot know it) and a monthly limit in
hours, then **Run a test job**. The test makes a one-minute video on your computer (nothing of yours), runs it on
the worker, brings the clip back, checks it plays and deletes it there, and shows which stages ran on the worker and
what the test cost. Then choose **Full Cloud**.

## Checks

- `curl -s https://worker.example.com/healthz` → `{"ok": true}`
- `curl -s https://worker.example.com/api/projects` → 404
- `curl -s https://worker.example.com/api/worker/v1/info` → 401 (no key)

## Stopping and restarts

- **Stop** on the project page stops the job on the worker and deletes it there.
- If the desktop closes or loses its connection while a job runs, the job carries on on the worker. When ClipForge
  starts again it picks the job up where it is (it never uploads the video a second time) and brings the clips back.
  A job nobody fetches is deleted after 72 hours.
- If the worker restarts, its unfinished jobs continue when it starts again.
