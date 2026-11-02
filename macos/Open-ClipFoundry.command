#!/bin/bash
set -eu
umask 077
cd -- "$(dirname -- "$0")"
trap 'status=$?; if [ "$status" -ne 0 ]; then echo "Setup stopped. Your saved data is unchanged. Keep this window to see the error."; fi; echo "Press Return to close."; read -r ignored' EXIT
echo "ClipFoundry — Apple silicon setup"
echo "Keep this Terminal window open while ClipFoundry runs."
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
  echo "This download requires an Apple-silicon Mac, opened outside Rosetta."
  exit 1
fi
major=$(sw_vers -productVersion | cut -d. -f1)
if [ "$major" -lt 14 ]; then echo "macOS 14 or newer is required."; exit 1; fi
for required in setup.py app.zip python-macos.tar.gz manifest.json; do
  if [ ! -f "$required" ]; then echo "Missing $required. Extract the entire ZIP before opening this file."; exit 1; fi
done
expected="__PYTHON_SHA256__"
actual=$(shasum -a 256 python-macos.tar.gz | cut -d' ' -f1)
if [ "$actual" != "$expected" ]; then echo "Python package verification failed. Download a fresh copy."; exit 1; fi
base="$HOME/Library/Application Support/ClipFoundry"
runtime="$base/runtime/python-${expected:0:16}"
mkdir -p "$base/runtime"
if [ ! -x "$runtime/python/bin/python3.12" ]; then
  scratch=$(mktemp -d "$base/runtime/.python-XXXXXX")
  tar -xzf python-macos.tar.gz -C "$scratch"
  # Publish only a completely extracted directory, even if two launchers start together.
  if ! ln -sh "$scratch" "$runtime" 2>/dev/null; then rm -rf "$scratch"; fi
  if [ ! -x "$runtime/python/bin/python3.12" ]; then
    echo "The private runtime is incomplete. Keep the data folder and download a fresh setup package."
    exit 1
  fi
fi
"$runtime/python/bin/python3.12" -I setup.py
