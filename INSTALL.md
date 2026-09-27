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
| Disk | ~3 GB (dependencies + Whisper model) | plus space for your videos |

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
ClipFoundry folder. You can also point to it in **Settings → FFmpeg location**.

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

Which model is used automatically:

* NVIDIA GPU detected → `large-v3-turbo` (float16) on the GPU
* CPU only → `small` (int8). For a faster but less accurate run pick `base` in Settings; for better accuracy pick
  `medium`.

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
  under 5 GB, or if the GPU runs out of memory. You can also choose it in Settings.
* When it starts, the console says which mode it is in:

  ```
  Transcription: GPU mode - NVIDIA GeForce RTX 3050, 6 GB (CUDA)
                 faster-whisper large-v3-turbo, compute type float16
  ```

  Whenever CTranslate2 reports a CUDA device, ClipFoundry uses GPU mode. If a CUDA library looks missing, it adds a
  warning and the fix, but still tries the GPU first. It says `CPU mode` only when there is no usable CUDA device, or
  when Settings → Transcription → Device is set to *CPU*. The Dashboard's *System* panel shows the same information.
  After updating ClipFoundry, close the old console window and run `start.bat` again, then reload the page
  (Ctrl+F5). An old window keeps running the old version.
* Each transcription logs the device and compute type it actually used (`Transcription starting: device=cuda
  compute_type=float16 model=large-v3-turbo`), plus its speed when it finishes. If the GPU fails partway through, the
  job continues on the CPU (`int8`). The console, the project page and the Dashboard all show a warning with the
  reason, so a fallback is never silent.
* **Video encoding (NVENC)** is used automatically when your FFmpeg build and driver support it (Settings → Video
  encoder).

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
  **Settings → AI scoring** choose *Ollama* and click *Test connection*.
* **LM Studio**: load a model, start the local server (default `http://localhost:1234/v1`), choose
  *LM Studio / OpenAI-compatible*, and enter the model name.

Only the 8-12 strongest candidate clips are sent to the model, never the full transcript.

## Optional: Claude API (paid)

Choose *Claude API* in Settings and paste an API key. This costs money per call. Use *Max candidates* to cap how many
clips per video are sent. The key is stored only in your local `data\clipfoundry.db`.

## Where things are stored

Everything lives in the `data` folder next to the app (override it with the `CLIPFOUNDRY_DATA` environment variable):

```
data\clipfoundry.db            projects, clips, metadata, settings
data\projects\<id>\            source video, transcript, candidates, rendered clips, exports
data\models\                   downloaded Whisper models
```

To back up, copy the `data` folder. Deleting a project in the UI removes its folder.

## Updating

Replace the app files (or `git pull`) but keep `data\`. `start.bat` notices a changed `requirements.txt` and updates
dependencies automatically.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| "FFmpeg was not found" | `winget install Gyan.FFmpeg`, then reopen the terminal; or set Settings → FFmpeg location. |
| Captions missing or wrong font | Use a full FFmpeg build (it needs `libass`). Gyan's builds include it. |
| Console says `CPU mode` although you have an NVIDIA GPU | Read the `Reason:` line. Usually run `start.bat` again (it installs the GPU libraries), or `.venv\Scripts\python -m pip install -r requirements-gpu.txt`. Also check Settings → Transcription → Device is *Auto*. |
| `cublas64_12.dll` / `cudnn` errors | Same as above. A CUDA 13 toolkit does not provide these CUDA 12 files. Meanwhile ClipFoundry falls back to CPU and shows a warning. |
| "NVIDIA GPU was found by the driver, but CUDA is not usable" | Install the latest NVIDIA driver. |
| Task Manager shows 0% GPU during transcription | Switch a GPU graph from "3D" to "Cuda"/"Compute_0", or run `gpu-check.bat`. |
| Out of memory on GPU | Settings → Model: `small` or `medium`, or Compute type `int8_float16`. |
| Port 8765 already in use | `start.bat --port 8877` |
| Nothing happens after upload | Check the console window for errors. Only one job runs at a time; others wait in the queue. |
| Re-running the setup | Delete the `.venv` folder and run `start.bat` again. |

## Linux / macOS

`./start.sh` does the same as `start.bat` (install `ffmpeg` with your package manager first). GPU transcription on
Linux uses the same `requirements-gpu.txt`.
