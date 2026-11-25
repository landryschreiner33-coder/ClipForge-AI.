# Processing: Local, Hybrid and Full Cloud

Settings → Processing chooses where **Make clips** runs.

| Mode | What runs where |
|---|---|
| Local | Everything on this computer (the default). |
| Hybrid | Clips are made here; pictures and video for animated shorts and the other makers are made on the cloud computer (Settings → Cloud computer, [CLOUD_GPU.md](CLOUD_GPU.md)). Choosing Hybrid switches `engines_comfyui` to `remote`; choosing Local switches it back to ClipForge's own ComfyUI. |
| Full Cloud | Make clips runs on the owner's own **ClipForge worker**: getting the video, transcription, finding the moments, framing, captions and rendering. The clips come back into the project here. |

Setting up a worker: [deploy/WORKER.md](../../deploy/WORKER.md).

## How a Full Cloud project runs

`jobs.Worker.submit_project` asks `fullcloud.runner.decide(project_id)` once, when the project is queued: with
Full Cloud chosen and a worker set up, the project's `info.processing` becomes `full_cloud` and `_run_project`
hands it to `runner.run` instead of `process.run_project`. A project keeps the mode it was queued with
(Reprocess decides again).

1. **Estimate and limit** (`usage.py`): the video's length × this worker's own ratio (worker seconds per second of
   video, the middle of its last ten jobs; 0.6 before it has done one), at least a minute. A job that would go over
   this month's hours never starts and nothing is sent.
2. **Check and upload** (`client.py`): `GET /api/worker/v1/info`, then one multipart `POST /jobs` with the video
   (or the link), the transcript file if the project has one, the project's options (`OPTION_KEYS`), the clip
   choices from Settings (`SETTING_KEYS`) and the project's guidance snapshot reduced by `runner.lean_guidance`
   (values and the deciding level's id, no names). Upload progress is the project's progress bar.
3. **Follow** (`runner._follow`): the worker's job is an ordinary project in its own data folder, run by its own job
   thread. The desktop polls it and shows its stage and message (`Worker: …`) on the project page; each new message
   goes into the Full Cloud log. Worker time is measured on the worker's clock from the job's start to its end.
4. **Bring back** (`runner._fetch`): `GET /jobs/{id}/result` gives the project facts, every clip with its rows
   (`clips` and `CHILDREN`), the candidates and each clip folder's files. Files are downloaded into a staging folder,
   then rows are written with the worker's folder and project id replaced by this computer's, clip ids kept, and the
   folders moved into `projects/<id>/clips/<clip_id>/`. A link's video comes back too, so edits render here.
   Render info's Brain notes are named from this computer's snapshot.
5. **Delete there**: `DELETE /jobs/{id}`. The run is recorded in `cloud_runs` (status, seconds, bytes, estimate).

Stop (Cancel processing) cancels and deletes the job on the worker. If the desktop closes or loses the
connection, the job carries on there: on the next start `worker.resume` runs the project again, `runner.run` sees
`info.cloud.job` and phase `running`/`fetching` and picks it up ("Picked up the job on the worker again") without
uploading again. Stop on such a project while it still waits in the queue stops and deletes the job there too
(`runner.stop_waiting`). A worker restart resumes its own jobs. A job never fetched is deleted after 72 hours
(`worker_api.KEEP_HOURS`), checked at the worker's start, every hour and on each `info` or new job.

What the desktop takes from a worker's answer is checked first (`runner.checked`): the answer is for the job asked
for, every clip id is an id, every file name is a plain name inside the clip's folder, the project's files are the
known three; otherwise nothing is changed. Rows are written in one transaction, and their JSON is read and written
again with this computer's folder (never changed as text). The worker checks the key and the upload size before it
reads the body (`WorkerOnly`), and the desktop does not start an upload over the worker's `max_upload_gb`.

What `info.cloud` holds (the project page's Full Cloud card, `runner.view`): phase (`waiting`, `upload`, `running`,
`fetching`, `done`, `failed`, `canceled`, `gone`), worker host, what was uploaded, estimate, worker seconds and cost,
which stages ran (`ran`) and how (`how`, e.g. `transcribe: import:srt`), the log (last 150 lines), the worker's
transcription model and AI, and what stays on this computer (`runner.UNSUPPORTED`).

## The worker side (`fullcloud/worker_api.py`)

A ClipForge started with `CLIPFOUNDRY_WORKER_KEY` (24 characters or more):

- `WorkerOnly` middleware: every address except `/api/worker/v1/...` and `/healthz` answers 404, websockets are
  refused, so the app's pages and API (no sign-in on a desktop) are not reachable.
- Every worker route needs `Authorization: Bearer <key>` (constant-time compare), else 401.
- Publishing, Autopilot, the phone listener and the editing apps' download do not start (`api.lifespan`).
- `apply_settings` writes the job's clip choices into the worker's settings just before the job runs.

| Route | What it does |
|---|---|
| `GET /api/worker/v1/info` | version, stages, transcription plan, AI label, upload limit, keep hours, busy, job counts |
| `POST /api/worker/v1/jobs` | start a job (multipart: `source` or `link`, `transcript`, `options`, `settings`, `name`, `clip_mode`, `guidance`) |
| `GET /api/worker/v1/jobs/{id}` | status, stage, progress, message, `ran`, `how`, started/ended on the worker's clock |
| `POST /api/worker/v1/jobs/{id}/cancel` | stop it |
| `GET /api/worker/v1/jobs/{id}/result` | rows and file lists (409 until ready) |
| `GET /api/worker/v1/jobs/{id}/files/{name}`, `/clips/{clip}/{name}` | one file |
| `DELETE /api/worker/v1/jobs/{id}` | delete the job and its folder |

## Settings → Processing (`fullcloud/routes.py`, `ProcessingSettings.tsx`)

| Route | |
|---|---|
| `GET /api/processing?check=` | modes and whether each is ready, worker (address, host, key set, check), price, monthly hours, usage this month with recent runs, stages, unsupported list, last test |
| `PUT /api/processing` | `mode`, `price_per_hour`, `month_hours` (ClipForge's own page only) |
| `POST /api/processing/worker` | address and key; `http://` only for this computer; a new address forgets the key; empty address removes the worker (and leaves Full Cloud) |
| `POST /api/processing/test`, `/test/stop` | the private test job (`testjob.py`, a studio job) |

The address and key are `ACTION_ONLY_KEYS` (only these routes set them), the key is a sealed `SECRET_KEYS` entry
never returned to the page, and the address is in `UNSHOWN_KEYS`.

**Test job**: a one-minute video made here (a moving test pattern with `TEST_SCRIPT` read by this computer's voice;
without a voice, a tone and the words as an SRT, and the result says transcription was not tried), sent as a
one-clip job; the clip comes back, is probed (picture, sound, length) and the job is deleted there. The result
lists which stages ran on the worker, upload speed, worker time, cost at the owner's price and the round trip.

## What stays on this computer

`runner.UNSUPPORTED`, shown in Settings and on each project: publishing, scheduling and accounts; Autopilot and
live streams; animated shorts, Text Stories, Make a YouTube video and FilmCraft (their pictures and video can use
the cloud computer: Hybrid); editing a clip and rendering it again; the Brain's own clip picking and ClipForge AI
keys (the worker picks clips with its own transcription model and AI setup).

## Tests

`tests/test_full_cloud.py` starts a real worker (uvicorn in a second process with its own data folder and key):
worker-only answers and the key; the same footage made here and on the worker gives the same clips (starts, ends,
titles), whose files are in this computer's folders and play, and an edit renders again here; a job the desktop
lost track of is picked up without a second upload; Stop deletes the job there; the private test job shows every
stage ran there; the monthly limit and estimates; a job over the limit never reaches the worker; the Processing
routes; the worker gets the style values but not the names behind them.

## Limits

- Not run on a rented server yet: the tests and the screenshots use a real worker on the same machine.
- Worker time and cost are what the worker measured and the owner's own hourly price; ClipForge cannot see a
  provider's bill. The monthly limit is checked before a job starts; a running job is not stopped when it passes.
- One video upload is one request: a proxy in front of the worker must allow its size (deploy/WORKER.md).
- The worker's clip picking uses its own Brain (empty) and AI setup, so the Brain-led steer and lessons from this
  computer do not apply in Full Cloud; style choices do.
