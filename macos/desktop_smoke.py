"""Native bundled-app integration, synthetic media and throwaway data only."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def is_listening(port):
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1', port)) == 0


def main(app: Path, evidence: Path):
    evidence.mkdir(parents=True, exist_ok=True)
    contents = app / 'Contents'
    python = contents / 'Frameworks/Python/bin/python3.12'
    source = contents / 'Resources/app'
    with tempfile.TemporaryDirectory(prefix='clipfoundry-desktop-test-') as tmp:
        env = dict(os.environ, CLIPFOUNDRY_DATA=tmp + '/diagnostics', CLIPFOUNDRY_WORKERS='off',
                   PYTHONDONTWRITEBYTECODE='1', CLIPFOUNDRY_FFMPEG=str(contents / 'Helpers'),
                   FONTCONFIG_FILE=str(contents / 'Resources/media/fonts.conf'))
        for script in ('diagnose.py', 'native_smoke.py'):
            subprocess.run([str(python), str(source / 'macos' / script)], cwd=source, env=env, check=True, timeout=150)
        executable = str(contents / 'MacOS/ClipFoundry')
        port = free_port()
        env.update(CLIPFOUNDRY_DESKTOP_TEST_BASE=tmp + '/studio', CLIPFOUNDRY_DESKTOP_TEST_PORT=str(port),
                   CLIPFOUNDRY_DESKTOP_EVIDENCE=str(evidence))
        with (evidence / 'native-window.log').open('w') as logs:
            subprocess.run([executable, '--smoke-test'], env=env, stdout=logs, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        assert (evidence / 'webview-passed.txt').is_file(), 'Native window failed; see native-window.log'
        assert not is_listening(port), 'Quit left a listening backend'
        print('Native window loaded full UI and Quit cleaned its owned backend.', flush=True)
        # Force Quit is separate from clean Quit: the Python parent guard must notice.
        (evidence / 'webview-passed.txt').unlink()
        with (evidence / 'force-quit.log').open('w') as logs:
            proc = subprocess.Popen([executable, '--smoke-test'], env=env, stdout=logs, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise RuntimeError('Second native launch exited early')
                    if is_listening(port):
                        break
                    time.sleep(.2)
                else:
                    raise RuntimeError('Second native launch did not start')
                proc.kill()
                proc.wait(timeout=10)
                deadline = time.monotonic() + 40
                while is_listening(port) and time.monotonic() < deadline:
                    time.sleep(.2)
                assert not is_listening(port), 'Force Quit left an orphan backend'
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=30)
        print('Force Quit cleaned the owned backend; second launch reused existing profile.', flush=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
        (evidence / 'native-checks.json').write_text(json.dumps({'webview': True, 'quit_cleanup': True,
            'force_quit_cleanup': True, 'bundle_unchanged': True, 'notarized': False}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    main(args.app.resolve(), args.evidence.resolve())
