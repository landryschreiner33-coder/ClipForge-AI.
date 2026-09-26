#!/usr/bin/env bash
# ClipFoundry launcher for Linux / macOS (Windows users: double-click start.bat).
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || { echo "Python 3.10+ is required"; exit 1; }
command -v ffmpeg >/dev/null || echo "[!] ffmpeg not found - install it (apt install ffmpeg / brew install ffmpeg)"

[ -x .venv/bin/python ] || "$PY" -m venv .venv
if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
  cp requirements.txt .venv/installed-requirements.txt
fi

# NVIDIA GPU: CUDA 12 cuBLAS/cuDNN for faster-whisper (from pip, whatever CUDA Toolkit is installed)
if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then
  if ! cmp -s requirements-gpu.txt .venv/installed-gpu-requirements.txt; then
    echo "NVIDIA GPU found - installing the CUDA libraries for GPU transcription (one-time, about 1 GB)"
    .venv/bin/python -m pip install -r requirements-gpu.txt \
      && cp requirements-gpu.txt .venv/installed-gpu-requirements.txt \
      || echo "[!] Could not install the GPU libraries - transcription will use the CPU"
  fi
fi

if [ ! -f frontend/dist/index.html ] && command -v npm >/dev/null; then
  (cd frontend && npm install && npm run build)
fi

exec .venv/bin/python -m clipfoundry --open "$@"
