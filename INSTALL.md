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
| GPU | not required | NVIDIA RTX (CUDA 12 driver) for fast transcription and NVENC encoding |
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
3. starts the server and opens <http://127.0.0.1:8765> in your browser.

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

## Optional: NVIDIA GPU acceleration

* **Video encoding (NVENC)** is used automatically when your FFmpeg build and driver support it (Settings → Video
  encoder).
* **Transcription on the GPU** needs the CUDA 12 cuBLAS and cuDNN 9 libraries. The easiest way is pip:

  ```powershell
  .venv\Scripts\python -m pip install -r requirements-gpu.txt
  ```

  ClipFoundry registers these DLLs automatically. If the GPU can't be used for any reason, transcription falls back
  to the CPU on its own. The Dashboard's *System* panel shows what was detected.

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
| GPU not used for transcription | Install `requirements-gpu.txt`, update the NVIDIA driver, and check Dashboard → System. |
| `cublas64_12.dll` / `cudnn` errors | Same as above. ClipFoundry falls back to CPU automatically meanwhile. |
| Out of memory on GPU | Settings → Model: `small` or `medium`, or Compute type `int8_float16`. |
| Port 8765 already in use | `start.bat --port 8877` |
| Nothing happens after upload | Check the console window for errors. Only one job runs at a time; others wait in the queue. |
| Re-running the setup | Delete the `.venv` folder and run `start.bat` again. |

## Linux / macOS

`./start.sh` does the same as `start.bat` (install `ffmpeg` with your package manager first). GPU transcription on
Linux uses the same `requirements-gpu.txt`.
