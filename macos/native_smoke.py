"""Native platform integration using temporary credentials/data, never an owner account."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipfoundry import awake, config, macos_secrets, secure

identifier = hashlib.sha256(str(config.data_dir().resolve()).encode()).hexdigest()[:32]
try:
    encrypted = secure.seal("synthetic-ci-secret")
    assert encrypted.startswith(macos_secrets.PREFIX)
    assert secure.unseal(encrypted) == "synthetic-ci-secret"
finally:
    # This is an ephemeral runner's test-only key, never a signed-in social account.
    backend = macos_secrets._backend()
    if backend.get_password(macos_secrets.SERVICE, identifier) is not None:
        backend.delete_password(macos_secrets.SERVICE, identifier)
print("Native login Keychain encryption round trip passed.", flush=True)
keeper = awake.KeepAwake()
try:
    assert keeper.hold(True) and keeper.status(True) == "on"
finally:
    keeper.hold(False)
print("Native idle-sleep request and release passed.", flush=True)
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
proc = subprocess.Popen([sys.executable, "-m", "clipfoundry", "--port", str(port)])
try:
    for attempt in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as response:
                health = json.load(response)
            break
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError("Native app exited before becoming healthy")
            time.sleep(0.5)
    else:
        raise RuntimeError("Native app never became ready")
    assert health["platform"] == "darwin" and health["ffmpeg"] and health["ffprobe"]
    print(json.dumps({key: health.get(key) for key in ["platform", "ffmpeg", "ffprobe", "videotoolbox"]}))
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
        assert b"ClipFoundry" in response.read()
    print("Native HTTP API and bundled frontend passed.", flush=True)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
