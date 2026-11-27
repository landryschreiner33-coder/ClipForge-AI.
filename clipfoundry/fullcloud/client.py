"""This computer talking to the owner's ClipForge worker (fullcloud/worker_api.py).

The address and key come from Settings → Processing (only ever from ClipForge's own page). The key goes only to that
address, in the Authorization header, over https (plain http only to this computer, for a tunnel). Each call says in
plain words what went wrong; a dropped connection is WorkerLost, so the caller can wait and look again (the work goes
on there).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, IO
from urllib.parse import urlsplit

import httpx

from .. import db
from .worker_api import API

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
UPLOAD_TIMEOUT = httpx.Timeout(600.0, connect=15.0)
CHUNK = 1024 * 1024


class WorkerError(Exception):
    """The worker refused or failed, in words for the owner."""

    status = 409


class WorkerLost(WorkerError):
    """The worker did not answer (the connection dropped or it is off)."""

    status = 503


def configured(settings: dict | None = None) -> dict | None:
    """{"url", "key", "host"} when a worker is set up; else None."""
    s = settings if settings is not None else db.get_settings()
    url = str(s.get("worker_url") or "").rstrip("/")
    if not url:
        return None
    return {"url": url, "key": str(s.get("worker_key") or ""), "host": host(url)}


def host(url: str) -> str:
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


class Client:
    def __init__(self, url: str, key: str, *, transport: httpx.BaseTransport | None = None):
        self.base = url.rstrip("/") + API
        self.headers = {"Authorization": f"Bearer {key}", "User-Agent": "ClipForge"}
        self.transport = transport

    @classmethod
    def from_settings(cls, settings: dict | None = None) -> "Client":
        cfg = configured(settings)
        if not cfg:
            raise WorkerError("No worker is set up. Add its address and key in Settings → Processing.")
        return cls(cfg["url"], cfg["key"])

    def _http(self, timeout=TIMEOUT) -> httpx.Client:
        return httpx.Client(timeout=timeout, headers=self.headers, transport=self.transport, follow_redirects=False)

    def _call(self, method: str, path: str, *, timeout=TIMEOUT, **kw) -> dict:
        try:
            with self._http(timeout) as http:
                r = http.request(method, self.base + path, **kw)
        except (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError,
                httpx.TimeoutException) as exc:
            raise WorkerLost(f"The worker did not answer ({type(exc).__name__}).") from exc
        except httpx.HTTPError as exc:
            raise WorkerError(f"The worker could not be reached ({exc}).") from exc
        return _answer(r)

    def info(self) -> dict:
        return self._call("GET", "/info")

    def job(self, job_id: str) -> dict:
        return self._call("GET", f"/jobs/{job_id}")

    def cancel(self, job_id: str) -> dict:
        return self._call("POST", f"/jobs/{job_id}/cancel")

    def delete(self, job_id: str) -> dict:
        return self._call("DELETE", f"/jobs/{job_id}")

    def result(self, job_id: str) -> dict:
        return self._call("GET", f"/jobs/{job_id}/result", timeout=httpx.Timeout(120.0, connect=10.0))

    def submit(self, *, source: Path | None = None, link: str = "", transcript: Path | None = None,
               options: dict, settings: dict, name: str = "", clip_mode: str = "highlights",
               guidance: dict | None = None, progress: Callable[[int, int], None] | None = None,
               cancel: Callable[[], bool] | None = None) -> dict:
        """Start a job: upload `source` (with `progress(sent, total)`) or send `link`."""
        import json

        data = {"options": json.dumps(options), "settings": json.dumps(settings), "name": name, "link": link,
                "clip_mode": clip_mode, "guidance": json.dumps(guidance or {})}
        files = {}
        handles: list[IO] = []
        try:
            if source is not None:
                fh = _Counting(open(source, "rb"), source.stat().st_size, progress, cancel)
                handles.append(fh)
                files["source"] = (source.name, fh, "application/octet-stream")
            if transcript is not None:
                th = open(transcript, "rb")
                handles.append(th)
                files["transcript"] = (transcript.name, th, "application/octet-stream")
            return self._call("POST", "/jobs", timeout=UPLOAD_TIMEOUT, data=data, files=files or None)
        finally:
            for h in handles:
                h.close()

    def download(self, path: str, dest: Path, *, cancel: Callable[[], bool] | None = None,
                 progress: Callable[[int], None] | None = None) -> int:
        """Fetch one file of a job into `dest` (whole or not at all); its size."""
        tmp = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        got = 0
        try:
            with self._http(httpx.Timeout(120.0, connect=10.0)) as http, http.stream("GET", self.base + path) as r:
                if r.status_code != 200:
                    r.read()
                    _answer(r)
                with open(tmp, "wb") as out:
                    for chunk in r.iter_bytes(CHUNK):
                        if cancel and cancel():
                            raise Stopped()
                        out.write(chunk)
                        got += len(chunk)
                        if progress:
                            progress(got)
            tmp.replace(dest)
            return got
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError, httpx.TimeoutException) as exc:
            raise WorkerLost(f"The worker stopped sending a file ({type(exc).__name__}).") from exc
        finally:
            tmp.unlink(missing_ok=True)


class Stopped(Exception):
    """The owner stopped the job while a file was moving."""


class _Counting:
    """A file that reports how much of it was read (the upload's progress) and stops when asked."""

    def __init__(self, fh: IO, total: int, progress, cancel):
        self.fh, self.total, self.progress, self.cancel = fh, total, progress, cancel
        self.sent = 0
        self._last = 0.0

    def read(self, n: int = -1) -> bytes:
        if self.cancel and self.cancel():
            raise Stopped()
        chunk = self.fh.read(n if n and n > 0 else CHUNK)
        self.sent += len(chunk)
        now = time.time()
        if self.progress and (now - self._last > 0.3 or not chunk):
            self._last = now
            self.progress(self.sent, self.total)
        return chunk

    def close(self) -> None:
        self.fh.close()

    def __getattr__(self, name):
        return getattr(self.fh, name)


def _answer(r: httpx.Response) -> dict:
    if r.status_code == 401:
        raise WorkerError("The worker refused the key. Copy CLIPFOUNDRY_WORKER_KEY from the worker into Settings → "
                          "Processing again.")
    if r.status_code == 404 and not r.headers.get("content-type", "").startswith("application/json"):
        raise WorkerError("That address answers, but it is not a ClipForge worker (or its key is not set there).")
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 500:
        raise WorkerLost(f"The worker had a problem ({r.status_code}).")
    if r.status_code >= 400:
        detail = body.get("detail") if isinstance(body, dict) else ""
        if r.status_code == 404 and detail == "Not Found":
            raise WorkerError("That address answers, but it is not a ClipForge worker (or its key is not set "
                              "there).")
        err = WorkerError(str(detail or f"The worker answered {r.status_code}.")[:400])
        err.status = 404 if r.status_code == 404 else 409
        raise err
    if not isinstance(body, dict):
        raise WorkerError("The worker's answer could not be read.")
    return body
