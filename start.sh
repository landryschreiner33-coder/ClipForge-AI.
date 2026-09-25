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

if [ ! -f frontend/dist/index.html ] && command -v npm >/dev/null; then
  (cd frontend && npm install && npm run build)
fi

exec .venv/bin/python -m clipfoundry --open "$@"
