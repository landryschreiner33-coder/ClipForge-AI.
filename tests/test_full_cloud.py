"""Full Cloud (fullcloud/): Make clips on the owner's own ClipForge worker.

A real worker runs in a second process (uvicorn, its own data folder, CLIPFOUNDRY_WORKER_KEY set); this process is
the desktop. The same footage is made into clips here and on the worker and must give the same clips; the worker's
clips come back with their files and rows and play; the worker answers only worker requests with its key; a job the
desktop lost track of (a restart) is picked up again without sending the video twice; Stop stops it there; the
monthly limit keeps a job from starting; the private test job proves every stage ran on the worker.

The footage is ClipForge's own test pattern with a tone and a transcript file, so no speech model is needed on either
side (the worker's meaning model is off, like the desktop's in tests).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
KEY = "test-worker-key-0123456789abcdef"
SENTENCES = [
    "Here is the secret nobody tells you about starting a channel.",
    "Most people quit after ten videos because nobody watches.",
    "But the numbers say something different.",
    "The first hundred videos are practice, and practice is supposed to be quiet.",
    "So here is what I did instead.",
    "I made one video every day for a year, no matter what.",
    "Some days it was terrible, and I posted it anyway.",
    "By day two hundred, something changed.",
    "A single video got a million views overnight.",
    "And it was not my best one.",
    "It was the one where I told the truth about failing.",
    "That is the lesson: people share honesty, not polish.",
    "Wait, it gets better.",
    "The next week, three more videos took off.",
    "Every one of them started with a mistake I made.",
    "So if you are scared to post, post the scary thing.",
    "That is the whole secret.",
    "Now go make your first video today.",
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def worker(tmp_path):
    data = tmp_path / "worker-data"
    env = {**os.environ, "CLIPFOUNDRY_DATA": str(data), "CLIPFOUNDRY_WORKER_KEY": KEY, "CLIPFOUNDRY_WORKERS": "off"}
    env.pop("CLIPFOUNDRY_MODE", None)
    subprocess.run([sys.executable, "-c", "from clipfoundry import db; db.init(); "
                                          "db.save_settings({'meaning_model': False})"], env=env, cwd=ROOT, check=True)
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "clipfoundry.api:app", "--port", str(port),
                             "--log-level", "warning"], cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            if httpx.get(url + "/healthz", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    else:
        proc.kill()
        raise RuntimeError("the worker did not start")
    try:
        yield {"url": url, "data": data}
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture()
def desk(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "desk-data"))
    from clipfoundry import db

    db.init()
    db.save_settings({"meaning_model": False})
    return tmp_path


def _footage(folder: Path, seconds: float = 72.0) -> tuple[Path, Path]:
    from clipfoundry.pipeline import ffmpeg_utils

    video = folder / "talk.mp4"
    ffmpeg_utils.run(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i",
                      f"sine=frequency=220:duration={seconds}", "-t", str(seconds), "-c:v", "libx264", "-preset",
                      "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], duration=seconds)
    srt = folder / "talk.srt"
    per = seconds / len(SENTENCES)
    lines = []
    for i, s in enumerate(SENTENCES):
        a, b = i * per, (i + 1) * per - 0.2
        lines.append(f"{i + 1}\n{_ts(a)} --> {_ts(b)}\n{s}\n")
    srt.write_text("\n".join(lines), encoding="utf-8")
    return video, srt


def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


OPTIONS = '{"clip_count": 2, "min_duration": 15, "target_duration": 22, "max_duration": 35}'


def _make(c, video: Path, srt: Path) -> str:
    with open(video, "rb") as v, open(srt, "rb") as t:
        r = c.post("/api/projects", files={"file": ("talk.mp4", v, "video/mp4"),
                                           "transcript": ("talk.srt", t, "text/plain")}, data={"options": OPTIONS})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _wait(project_id: str, timeout: float = 300.0, until=("ready", "error", "cancelled")) -> dict:
    from clipfoundry import db

    end = time.time() + timeout
    while time.time() < end:
        p = db.get_project(project_id)
        if p["status"] in until:
            return p
        time.sleep(0.5)
    raise AssertionError(f"still {db.get_project(project_id)['status']}: {db.get_project(project_id)['message']}")


def _use_worker(worker, **more) -> None:
    from clipfoundry import db

    db.save_settings({"worker_url": worker["url"], "worker_key": KEY, "processing_mode": "full_cloud", **more})


def _worker_jobs(worker) -> dict:
    return httpx.get(worker["url"] + "/api/worker/v1/info", headers={"Authorization": f"Bearer {KEY}"}).json()["jobs"]


@pytest.mark.slow
def test_the_worker_answers_only_worker_requests_with_its_key(worker, desk):
    from clipfoundry.fullcloud import client

    base = worker["url"]
    assert httpx.get(base + "/api/worker/v1/info").status_code == 401
    assert httpx.get(base + "/api/worker/v1/info", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert httpx.get(base + "/api/projects").status_code == 404  # the app's own API is not there to the internet
    assert httpx.get(base + "/api/settings").status_code == 404
    assert httpx.get(base + "/").status_code == 404
    facts = client.Client(base, KEY).info()
    assert facts["worker"] and facts["stages"] == ["ingest", "transcribe", "analyze", "framing", "captions", "render"]
    with pytest.raises(client.WorkerError, match="refused the key"):
        client.Client(base, "not-the-key").info()


@pytest.mark.slow
def test_the_same_footage_makes_the_same_clips_here_and_on_the_worker(worker, desk):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.pipeline import ffmpeg_utils

    video, srt = _footage(desk)
    c = TestClient(app)
    here = _wait(_make(c, video, srt))
    assert here["status"] == "ready", here["error"]
    assert not (here.get("info") or {}).get("cloud")
    local = db.list_clips(here["id"])
    assert local and all(cl["status"] == "ready" for cl in local)

    _use_worker(worker, worker_price_per_hour=1.2)
    there = _wait(_make(c, video, srt))
    assert there["status"] == "ready", there["error"]
    cloud = there["info"]["cloud"]
    assert cloud["phase"] == "done" and cloud["worker"] == "127.0.0.1"
    assert all(cloud["ran"][s] for s in ("ingest", "transcribe", "analyze", "framing", "captions", "render")), cloud
    assert cloud["how"]["transcribe"].startswith("import") and cloud["uploaded"][0]["name"] == "talk.mp4"
    assert cloud["seconds"] > 0 and cloud["cost"] is not None
    remote = db.list_clips(there["id"])
    assert [(round(a["start"], 2), round(a["end"], 2), a["title"]) for a in local] == \
        [(round(b["start"], 2), round(b["end"], 2), b["title"]) for b in remote]
    pdir = Path(there["source_path"]).parent
    for cl in remote:
        assert cl["status"] == "ready" and Path(cl["output_path"]).is_file()
        assert Path(cl["output_path"]).parent == pdir / "clips" / cl["id"]  # this computer's folder, not the worker's
        assert str(worker["data"]) not in str(cl["render_info"])
        meta = ffmpeg_utils.probe(cl["output_path"])
        assert meta["video_codec"] and meta["width"] > 0 and meta["has_audio"] and meta["duration"] > 10
    assert (pdir / "transcript.json").is_file()
    # the job and its files are gone from the worker; the run is counted
    assert _worker_jobs(worker) == {"waiting": 0, "finished": 0}
    runs = db.select("cloud_runs", "project_id = ?", (there["id"],))
    assert len(runs) == 1 and runs[0]["status"] == "done" and runs[0]["seconds"] > 0
    view = c.get(f"/api/projects/{there['id']}").json()["cloud"]
    assert view["phase"] == "done" and any("Brought back" in line["text"] for line in view["log"])
    # an edit renders again here, from this computer's copy of the video
    from clipfoundry.pipeline import process
    from clipfoundry.pipeline.common import JobContext

    process.render_single(remote[0]["id"], JobContext(None, lambda: False))
    assert db.get_clip(remote[0]["id"])["status"] == "ready"


@pytest.mark.slow
def test_a_job_the_desktop_lost_track_of_is_picked_up_without_sending_the_video_again(worker, desk):
    from clipfoundry import db
    from clipfoundry.fullcloud import client, runner
    from clipfoundry.jobs import worker as job_thread

    video, srt = _footage(desk)
    _use_worker(worker)
    p = db.create_project("talk", source_filename="talk.mp4", options={"clip_count": 1, "min_duration": 15.0,
                                                                     "target_duration": 22.0, "max_duration": 35.0})
    pdir = Path(os.environ["CLIPFOUNDRY_DATA"]) / "projects" / p["id"]
    pdir.mkdir(parents=True)
    src = pdir / "source.mp4"
    src.write_bytes(video.read_bytes())
    db.update_project(p["id"], source_path=str(src), status="processing")
    # the video was uploaded before ClipForge closed: the job is on the worker, the project knows its id
    job = client.Client(worker["url"], KEY).submit(source=src, transcript=srt, options={"clip_count": 1,
                                                                                       "min_duration": 15.0,
                                                                                       "target_duration": 22.0,
                                                                                       "max_duration": 35.0},
                                                   settings={})
    run = db.insert("cloud_runs", {"kind": "project", "project_id": p["id"], "worker": "127.0.0.1",
                                   "status": "running", "started_at": time.time(), "remote_id": job["id"]})
    db.update_project(p["id"], info={"processing": "full_cloud", "cloud": {"job": job["id"], "phase": "running",
                                                                           "worker": "127.0.0.1", "run": run["id"],
                                                                           "log": []}})
    job_thread.resume(db.interrupted_work())  # what the app does when it starts again
    done = _wait(p["id"])
    assert done["status"] == "ready", done["error"]
    log = [line["text"] for line in done["info"]["cloud"]["log"]]
    assert any("Picked up the job on the worker again" in t for t in log)
    assert not any(t.startswith("Uploaded") for t in log)  # never sent twice
    assert db.list_clips(p["id"]) and runner.state(p["id"])["phase"] == "done"
    assert db.fetch("cloud_runs", run["id"])["status"] == "done"


@pytest.mark.slow
def test_stop_stops_the_job_on_the_worker_and_deletes_it(worker, desk):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    video, srt = _footage(desk)
    _use_worker(worker)
    c = TestClient(app)
    pid = _make(c, video, srt)
    end = time.time() + 120
    while (db.get_project(pid)["info"].get("cloud") or {}).get("phase") != "running":
        assert time.time() < end, db.get_project(pid)
        time.sleep(0.2)
    assert c.post(f"/api/projects/{pid}/cancel").status_code == 200
    p = _wait(pid, until=("cancelled", "ready", "error"))
    assert p["status"] == "cancelled"
    assert p["info"]["cloud"]["phase"] == "canceled"
    assert _worker_jobs(worker) == {"waiting": 0, "finished": 0}
    assert db.select("cloud_runs", "project_id = ?", (pid,))[0]["status"] == "canceled"


@pytest.mark.slow
def test_the_private_test_job_proves_every_stage_ran_on_the_worker(worker, desk, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.fullcloud import testjob
    from clipfoundry.studio import jobs as studio_jobs

    import clipfoundry.makers.voice as voice

    def no_voice(*a, **k):
        raise RuntimeError("no voice in this test")

    monkeypatch.setattr(voice, "speak", no_voice)  # the worker would need a speech model to transcribe real speech
    _use_worker(worker, worker_price_per_hour=2.0)
    c = TestClient(app)
    from clipfoundry.jobs import worker as job_thread

    queued: list[str] = []
    monkeypatch.setattr(job_thread, "submit_studio", lambda job_id: queued.append(job_id))
    got = c.post("/api/processing/test", headers={"X-ClipFoundry": "1"})
    assert got.status_code == 200, got.text
    studio_jobs.run(queued.pop(0))
    t = c.get("/api/processing").json()["test"]
    assert t["status"] == "done" and t["ok"], t
    assert all(t["ran"][s] for s in ("ingest", "transcribe", "analyze", "framing", "captions", "render")), t["ran"]
    assert t["transcription_tried"] is False and "transcription was not tried" in t["note"]
    assert t["clip"]["plays"] and t["clip"]["seconds"] > 5 and t["clip"]["height"] > t["clip"]["width"]
    assert t["worker_seconds"] > 0 and t["cost"] is not None and t["upload_mbps"] > 0
    assert _worker_jobs(worker) == {"waiting": 0, "finished": 0}
    assert db.select("cloud_runs", "kind = 'test'")[0]["seconds"] > 0
    assert testjob.last()["status"] == "done"


def test_the_monthly_limit_and_the_estimate(desk):
    from clipfoundry import db
    from clipfoundry.fullcloud import usage

    s = {**db.get_settings(), "worker_month_hours": 1.0, "worker_price_per_hour": 0.6}
    est = usage.estimate(600, "w.example", s)
    assert est == {"seconds": 360, "cost": 0.06, "price": 0.6, "ratio": usage.DEFAULT_RATIO, "known": True}
    assert usage.estimate(None, "w.example", s)["known"] is False
    assert usage.limit_problem(s, need_seconds=est["seconds"]) == ""
    db.insert("cloud_runs", {"kind": "project", "worker": "w.example", "status": "done", "started_at": time.time(),
                             "seconds": 3400, "info": {"video_seconds": 3400 / 0.5}})
    assert usage.ratio("w.example") == 0.5  # learned from the worker's own jobs
    assert "needs about" in usage.limit_problem(s, need_seconds=600)
    db.insert("cloud_runs", {"kind": "project", "worker": "w.example", "status": "done", "started_at": time.time(),
                             "seconds": 400})
    assert "used up" in usage.limit_problem(s)
    assert "0 hours" in usage.limit_problem({**s, "worker_month_hours": 0})
    old = time.time() - 40 * 86400
    db.insert("cloud_runs", {"kind": "project", "worker": "w.example", "status": "done", "started_at": old,
                             "seconds": 99999})
    assert usage.used_seconds() == 3800  # last month's jobs do not count


def test_a_job_over_the_limit_never_reaches_the_worker(desk, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.fullcloud import client

    called = []
    monkeypatch.setattr(client.Client, "info", lambda self: called.append("info") or {"worker": True})
    monkeypatch.setattr(client.Client, "submit", lambda self, **k: called.append("submit"))
    db.save_settings({"worker_url": "https://worker.example", "worker_key": KEY, "processing_mode": "full_cloud",
                      "worker_month_hours": 0.01})
    video, srt = _footage(desk, 30.0)
    p = _wait(_make(TestClient(app), video, srt), 60)
    assert p["status"] == "error" and "needs about" in p["error"] and called == []
    assert db.select("cloud_runs") == []


def test_settings_processing_modes(desk):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    c = TestClient(app)
    h = {"X-ClipFoundry": "1"}
    v = c.get("/api/processing").json()
    assert v["mode"] == "local" and [m["id"] for m in v["modes"]] == ["local", "hybrid", "full_cloud"]
    assert not v["modes"][2]["ready"] and v["unsupported"]
    assert c.put("/api/processing", json={"mode": "full_cloud"}, headers=h).status_code == 409
    assert c.put("/api/processing", json={"mode": "hybrid"}, headers=h).status_code == 409
    assert c.put("/api/processing", json={"mode": "full_cloud"}).status_code == 403  # only from ClipForge's page
    bad = c.post("/api/processing/worker", json={"url": "http://worker.example", "key": KEY}, headers=h)
    assert bad.status_code == 422  # the key and the videos never cross the internet in clear
    ok = c.post("/api/processing/worker", json={"url": "worker.example", "key": KEY}, headers=h).json()
    assert ok["worker"]["url"] == "https://worker.example" and ok["worker"]["key_set"]
    assert ok["worker"]["check"]["ok"] is False  # nothing answers there
    assert KEY not in str(c.get("/api/processing").json()) and KEY not in str(c.get("/api/settings").json())
    moved = c.post("/api/processing/worker", json={"url": "https://other.example"}, headers=h).json()
    assert not moved["worker"]["key_set"]  # a key only ever goes to the worker it was typed for
    c.post("/api/processing/worker", json={"url": "https://other.example", "key": KEY}, headers=h)
    assert c.put("/api/processing", json={"mode": "full_cloud", "month_hours": 5, "price_per_hour": 0.44},
                 headers=h).json()["mode"] == "full_cloud"
    s = db.get_settings()
    assert s["worker_month_hours"] == 5.0 and s["worker_price_per_hour"] == 0.44
    db.save_settings({"engines_remote_url": "https://abc123def45-8188.proxy.runpod.net"})
    got = c.put("/api/processing", json={"mode": "hybrid"}, headers=h).json()
    assert got["mode"] == "hybrid" and db.get_settings()["engines_comfyui"] == "remote" and got["note"]
    got = c.put("/api/processing", json={"mode": "local"}, headers=h).json()
    assert db.get_settings()["engines_comfyui"] == "clipforge" and "this computer" in got["note"]
    off = c.post("/api/processing/worker", json={"url": ""}, headers=h).json()
    assert off["worker"]["url"] == "" and off["mode"] == "local"


def test_the_worker_gets_the_style_choices_but_not_the_names_behind_them():
    from clipfoundry.fullcloud import runner
    from clipfoundry.studio import guidance

    snap = {"schema": 1, "mode": "highlights", "values": {"caption_style": "bold", "layout": "split"},
            "decisions": [{"field": "caption_style", "value": "bold", "text": "Bold captions",
                           "from": {"level": "brain", "id": "k1", "revision": 3, "name": "My secret channel plan"},
                           "also": [], "overridden": []},
                          {"field": "layout", "value": "split", "text": "Split",
                           "from": {"level": "style", "id": "s1", "revision": 2, "name": "Podcast look"}}],
            "conflicts": [{"field": "x", "entries": [{"name": "Another note"}]}],
            "used": [{"name": "Podcast look"}], "entries": [{"name": "My secret channel plan"}]}
    lean = runner.lean_guidance(snap)
    assert "secret" not in str(lean) and "Podcast look" not in str(lean) and "Another note" not in str(lean)
    assert lean["values"] == snap["values"]
    assert guidance.render_values(lean) == {"caption_style": "bold", "layout": "split"}
    assert [b["knowledge_id"] for b in guidance.brain_influences(lean)] == ["k1"]
    assert runner.lean_guidance({}) == {}


# ------------------------------------------------------------------ what the desktop takes from a worker's answer
def _cloud_project(name: str = "cloud project") -> tuple[dict, Path]:
    from clipfoundry import config, db

    p = db.create_project(name)
    pdir = config.projects_dir() / p["id"]
    pdir.mkdir(parents=True)
    (pdir / "source.mp4").write_bytes(b"video")
    db.update_project(p["id"], source_path=str(pdir / "source.mp4"))
    return db.get_project(p["id"]), pdir


def _answering(result: dict):
    import httpx

    from clipfoundry.fullcloud import client

    asked: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        asked.append(req.url.path)
        if req.url.path.endswith("/result"):
            return httpx.Response(200, json=result)
        return httpx.Response(200, content=b"mp4")

    return client.Client("https://worker.example", "k" * 30, transport=httpx.MockTransport(handler)), asked


def _clip_row(cid: str, job: str, remote: str = "/srv/worker/projects/x", **more) -> dict:
    now = time.time()
    return {"id": cid, "project_id": job, "start": 0.0, "end": 10.0, "status": "ready", "title": "t",
            "created_at": now, "updated_at": now, **more}


@pytest.mark.parametrize("bad", ["../..", "..", "ABSOLUTE", "a" * 12 + "/x", "ABCDEF123456", ""])
def test_a_worker_answer_naming_a_path_outside_the_project_is_refused_and_nothing_changes(desk, bad):
    """A clip id from the worker becomes a folder here: '../..' once made the desktop delete the whole projects
    folder (another project's video with it), and an absolute path any folder at all. Every clip id must be an id,
    and nothing changes when one is not. The absolute path is a folder in this test's own temporary folder: should
    the check ever break again, the test deletes nothing outside it."""
    from clipfoundry import db
    from clipfoundry.fullcloud import runner
    from clipfoundry.pipeline.common import JobContext

    victim = desk / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("mine")
    bad = str(victim) if bad == "ABSOLUTE" else bad
    other, odir = _cloud_project("other project")
    p, pdir = _cloud_project()
    job = "1a2b3c4d5e6f"
    good = _clip_row("0123456789ab", job)
    res = {"job": {"id": job}, "dir": "/srv/worker/projects/" + job, "project": {}, "info": {}, "candidates": [],
           "files": [], "source": None,
           "clips": [{"row": good, "children": {}, "files": [{"name": "clip.mp4", "bytes": 3}]},
                     {"row": _clip_row(bad, job), "children": {}, "files": []}]}
    c, asked = _answering(res)
    with pytest.raises(runner.RemoteError, match="refused"):
        runner._fetch(p["id"], c, job, JobContext(None, lambda: False))
    assert (odir / "source.mp4").read_bytes() == b"video" and (victim / "keep.txt").read_text() == "mine"
    assert db.list_clips(p["id"]) == [] and asked == [f"/api/worker/v1/jobs/{job}/result"]  # nothing downloaded


@pytest.mark.parametrize("files, clip_files, job_said, folder", [
    (["ABSOLUTE"], [], None, None),  # a file in this test's own folder (see above)
    (["../../planted.txt"], [], None, None),
    ([], [{"name": "../clip.mp4", "bytes": 3}], None, None),
    ([], [{"name": ".hidden", "bytes": 3}], None, None),
    ([], [{"name": "a\\b.mp4", "bytes": 3}], None, None),
    ([], [], "ffffffffffff", None),  # an answer for another job
    ([], [], None, ""),  # no folder: replacing "" would put this computer's folder between every letter
])
def test_file_names_folders_and_job_ids_in_a_worker_answer_are_checked(desk, files, clip_files, job_said, folder):
    from clipfoundry import db
    from clipfoundry.fullcloud import runner
    from clipfoundry.pipeline.common import JobContext

    p, pdir = _cloud_project()
    files = [str(desk / "notes.txt") if n == "ABSOLUTE" else n for n in files]
    job = "1a2b3c4d5e6f"
    res = {"job": {"id": job_said or job}, "dir": "/srv/worker/projects/" + job if folder is None else folder,
           "project": {}, "info": {}, "candidates": [], "files": files, "source": None,
           "clips": [{"row": _clip_row("0123456789ab", job), "children": {}, "files": clip_files}]}
    c, asked = _answering(res)
    with pytest.raises(runner.RemoteError, match="refused"):
        runner._fetch(p["id"], c, job, JobContext(None, lambda: False))
    assert len(asked) == 1 and db.list_clips(p["id"]) == []


def test_a_windows_folder_in_the_clips_rows_stays_valid_json(monkeypatch, tmp_path):
    """The worker's rows hold JSON as text; its folder is swapped for this computer's in the decoded values, so a
    Windows folder's backslashes are escaped (swapping in the text made render_info unreadable on Windows, and a
    project with a guidance snapshot failed every time)."""
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / r"C:\Users\Sam\ClipForge\data"))
    from clipfoundry import db
    from clipfoundry.fullcloud import runner
    from clipfoundry.pipeline.common import JobContext

    db.init()
    p, pdir = _cloud_project()
    db.update_project(p["id"], guidance={"schema": 1, "mode": "highlights", "values": {}, "decisions": []})
    job, remote = "1a2b3c4d5e6f", "/var/lib/clipforge-worker/projects/1a2b3c4d5e6f"
    cid = "c1aaaaaaaaaa"
    row = _clip_row(cid, job, output_path=f"{remote}/clips/{cid}/clip.mp4",
                    render_info=json.dumps({"mode": "crop", "artifact": {"path": f"{remote}/clips/{cid}/clip.mp4"},
                                            "project": job}))
    res = {"job": {"id": job}, "dir": remote, "project": {}, "info": {"note": f"{remote}/transcript.json"},
           "candidates": [], "files": [], "source": None,
           "clips": [{"row": row, "children": {"clip_scores": [{"clip_id": "ffffffffffff", "final": 70.0,
                                                                 "updated_at": time.time(),
                                                                 "components": json.dumps({"path": remote})}]},
                      "files": [{"name": "clip.mp4", "bytes": 3}]}]}
    c, _ = _answering(res)
    assert runner._fetch(p["id"], c, job, JobContext(None, lambda: False)) == 1
    clip = db.get_clip(cid)
    assert clip["output_path"] == f"{pdir}/clips/{cid}/clip.mp4"
    assert clip["render_info"]["artifact"]["path"] == f"{pdir}/clips/{cid}/clip.mp4"
    assert clip["render_info"]["project"] == p["id"] and clip["render_info"]["brain_knowledge"] == []
    assert (pdir / "clips" / cid / "clip.mp4").read_bytes() == b"mp4"
    with db.connect() as conn:  # a child row belongs to the clip it came with, whatever clip id the worker wrote
        score = dict(conn.execute("SELECT clip_id, components FROM clip_scores").fetchone())
    assert score["clip_id"] == cid and json.loads(score["components"]) == {"path": str(pdir)}
    assert db.get_project(p["id"])["info"]["note"] == f"{pdir}/transcript.json"


# ------------------------------------------------------------------ worker time records and the project card
def _desk_worker(monkeypatch, *, submit=None, info=None):
    from clipfoundry import db
    from clipfoundry.fullcloud import client

    db.save_settings({"worker_url": "https://worker.example", "worker_key": KEY, "processing_mode": "full_cloud",
                      "worker_month_hours": 10})
    monkeypatch.setattr(client.Client, "info", lambda self: info or {"worker": True, "version": "t",
                                                                     "max_upload_gb": 20})
    if submit:
        monkeypatch.setattr(client.Client, "submit", submit)


@pytest.mark.parametrize("how", ["refused", "stopped"])
def test_a_run_that_fails_or_is_stopped_during_the_upload_closes_its_worker_time_record(desk, monkeypatch, how):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.fullcloud import client, runner
    from clipfoundry.pipeline.common import Cancelled, JobContext

    def submit(self, **kw):
        if how == "refused":
            raise client.WorkerError("The worker refused the key.")
        raise client.Stopped()

    _desk_worker(monkeypatch, submit=submit)
    p, _ = _cloud_project()
    assert runner.decide(p["id"]) == "full_cloud"
    with pytest.raises(Cancelled if how == "stopped" else client.WorkerError):
        runner.run(p["id"], None, JobContext(None, lambda: False))
    with db.connect() as conn:
        runs = [dict(r) for r in conn.execute("SELECT status, ended_at FROM cloud_runs")]
    assert runs == [{"status": "canceled" if how == "stopped" else "failed", "ended_at": runs[0]["ended_at"]}]
    assert runs[0]["ended_at"]
    db.update_project(p["id"], status="cancelled" if how == "stopped" else "error")
    card = TestClient(app).get(f"/api/projects/{p['id']}").json()["cloud"]
    assert card["phase"] == ("canceled" if how == "stopped" else "failed")


def test_a_video_over_the_workers_upload_limit_is_not_sent(desk, monkeypatch):
    from clipfoundry import db
    from clipfoundry.fullcloud import client, runner
    from clipfoundry.pipeline.common import JobContext

    sent = []
    _desk_worker(monkeypatch, submit=lambda self, **kw: sent.append(kw),
                 info={"worker": True, "version": "t", "max_upload_gb": 0.000001})
    p, pdir = _cloud_project()
    (pdir / "source.mp4").write_bytes(b"x" * 5000)
    runner.decide(p["id"])
    with pytest.raises(runner.RemoteError, match="takes videos up to"):
        runner.run(p["id"], None, JobContext(None, lambda: False))
    assert sent == [] and runner.state(p["id"])["phase"] == "failed"
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cloud_runs").fetchone()[0] == 0
    assert client  # imported for the patch


def test_a_project_made_here_again_shows_no_full_cloud_card(desk, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.fullcloud import runner

    _desk_worker(monkeypatch)
    p, _ = _cloud_project()
    runner.decide(p["id"])
    runner._save(p["id"], phase="done", worker="worker.example", seconds=30)
    c = TestClient(app)
    assert c.get(f"/api/projects/{p['id']}").json()["cloud"]["phase"] == "done"
    db.save_settings({"processing_mode": "local"})
    assert runner.decide(p["id"], again=True) == ""
    assert c.get(f"/api/projects/{p['id']}").json()["cloud"] is None


def test_stop_on_a_queued_project_whose_job_is_on_the_worker_stops_it_there(desk, monkeypatch):
    """After a restart a Full Cloud project waits in the queue to pick its job up again; Stop then must stop and
    delete the job on the worker too (it used to be marked cancelled here only, the worker kept working)."""
    from clipfoundry import db
    from clipfoundry.fullcloud import client, runner, usage
    from clipfoundry.jobs import Worker

    calls = []
    monkeypatch.setattr(client.Client, "cancel", lambda self, j: calls.append(("cancel", j)) or {})
    monkeypatch.setattr(client.Client, "delete", lambda self, j: calls.append(("delete", j)) or {})
    _desk_worker(monkeypatch)
    p, _ = _cloud_project()
    runner.decide(p["id"])
    run = usage.start("project", "worker.example", p["id"], {"seconds": 60, "cost": None, "known": False}, "local")
    usage.update(run["id"], status="running")
    runner._save(p["id"], phase="running", job="1a2b3c4d5e6f", run=run["id"], worker="worker.example")
    Worker()._mark_cancelled("project", p["id"])
    assert calls == [("cancel", "1a2b3c4d5e6f"), ("delete", "1a2b3c4d5e6f")]
    assert runner.state(p["id"])["phase"] == "canceled" and db.get_project(p["id"])["status"] == "cancelled"
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM cloud_runs").fetchone()[0] == "canceled"


def test_the_price_must_be_a_number(desk):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    c, h = TestClient(app), {"X-ClipFoundry": "1"}
    assert c.put("/api/processing", json={"price_per_hour": None, "month_hours": 10}, headers=h).status_code == 422
    assert c.put("/api/processing", json={"price_per_hour": "abc"}, headers=h).status_code == 422
    assert c.put("/api/processing", json={"price_per_hour": "0,44"}, headers=h).status_code == 200
    assert db.get_settings()["worker_price_per_hour"] == 0.44


# ------------------------------------------------------------------ the worker's own checks
def test_the_worker_checks_its_key_and_the_size_before_reading_an_upload(desk, monkeypatch):
    """FastAPI stores an upload before its route runs: without the key (or over the limit) nothing may reach the
    worker's disk, so WorkerOnly answers before the app reads the body."""
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.fullcloud import worker_api

    monkeypatch.setenv(worker_api.KEY_ENV, KEY)
    monkeypatch.setattr(worker_api, "MAX_UPLOAD_GB", 0.0001)  # about 100 KB, plus room for the choices
    read = []
    real = worker_api.WorkerOnly.__call__

    async def watching(self, scope, receive, send):
        async def counting():
            m = await receive()
            read.append(len(m.get("body") or b""))
            return m
        return await real(self, scope, counting, send)

    monkeypatch.setattr(worker_api.WorkerOnly, "__call__", watching)
    c = TestClient(app)
    files = {"source": ("v.mp4", b"x" * 1000, "video/mp4")}
    r = c.post("/api/worker/v1/jobs", files=files)
    assert r.status_code == 401 and read == []
    big = {"source": ("v.mp4", b"x" * (worker_api._body_limit() + 10), "video/mp4")}
    r = c.post("/api/worker/v1/jobs", files=big, headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 413 and read == [] and "limit" in r.json()["detail"]

    def chunked():  # no length given: stopped at the limit, not after the whole body
        for _ in range(400):
            yield b"y" * 4096

    r = c.post("/api/worker/v1/jobs", content=chunked(),
               headers={"Authorization": f"Bearer {KEY}", "Content-Type": "multipart/form-data; boundary=zz"})
    assert r.status_code in (400, 413) and sum(read) <= worker_api._body_limit() + 70_000
    assert not [p for p in db.list_projects() if (p.get("info") or {}).get("worker_job")]


def test_unfetched_jobs_are_deleted_after_three_days_without_a_new_job(desk, monkeypatch):
    from clipfoundry import config, db
    from clipfoundry.fullcloud import worker_api

    monkeypatch.setenv(worker_api.KEY_ENV, KEY)
    monkeypatch.setattr(worker_api, "_tidying", __import__("threading").Event())
    monkeypatch.setattr(worker_api, "TIDY_EVERY_S", 3600)
    p = db.create_project("job", info={"worker_job": {"settings": {}}}, status="error")
    pdir = config.projects_dir() / p["id"]
    pdir.mkdir(parents=True)
    (pdir / "source.mp4").write_bytes(b"v")
    db.update_project(p["id"], source_path=str(pdir / "source.mp4"))
    with db.connect() as conn:
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (time.time() - 80 * 3600, p["id"]))
    worker_api.start_tidying()  # what a worker does at start (api.lifespan), then every hour
    for _ in range(50):
        if not db.get_project(p["id"]):
            break
        time.sleep(0.1)
    assert db.get_project(p["id"]) is None and not pdir.exists()


def test_tidying_a_worker_job_never_deletes_a_folder_outside_the_projects_folder(desk, monkeypatch):
    """Safety (the Nov 25 incident): a row naming a file elsewhere loses only its row. Only tmp paths are used."""
    from clipfoundry import config, db
    from clipfoundry.fullcloud import worker_api

    monkeypatch.setenv(worker_api.KEY_ENV, KEY)
    outside = desk / "not-a-project"
    outside.mkdir()
    (outside / "keep.mp4").write_bytes(b"precious")
    p = db.create_project("job", info={"worker_job": {"settings": {}}}, status="error", source_path=str(
        outside / "keep.mp4"))
    with db.connect() as conn:
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (time.time() - 80 * 3600, p["id"]))
    assert worker_api.tidy() == 1
    assert db.get_project(p["id"]) is None and (outside / "keep.mp4").read_bytes() == b"precious"
    assert worker_api.own_folder(config.projects_dir() / "abc") and not worker_api.own_folder(outside)
    assert not worker_api.own_folder(config.projects_dir())
    assert not worker_api.own_folder(config.projects_dir() / "a" / "b")


def test_a_project_outside_its_own_folder_is_refused_before_anything_is_sent_and_never_stays_stuck(desk, monkeypatch):
    """Second review of the folder guard: such a project is refused before its video is uploaded (no worker time),
    and one refused when its clips come back ends its job, so Process again picks where to run afresh. Only this
    test's own temporary folder is used."""
    from clipfoundry import db
    from clipfoundry.fullcloud import runner
    from clipfoundry.pipeline.common import JobContext

    sent = []
    _desk_worker(monkeypatch, submit=lambda self, **kw: sent.append(kw))
    elsewhere = desk / "moved-data" / "projects" / "abc"
    elsewhere.mkdir(parents=True)
    (elsewhere / "source.mp4").write_bytes(b"video")
    p = db.create_project("moved")
    db.update_project(p["id"], source_path=str(elsewhere / "source.mp4"))
    assert runner.decide(p["id"]) == "full_cloud"
    with pytest.raises(runner.RemoteError, match="Switch to Local"):
        runner.run(p["id"], None, JobContext(None, lambda: False))
    assert sent == [] and runner.state(p["id"])["phase"] == "failed"
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cloud_runs").fetchone()[0] == 0
    # a job that finished on the worker while the folder moved: refused when it comes back, and ended there
    job = "1a2b3c4d5e6f"
    runner._save(p["id"], phase="fetching", job=job, worker="worker.example")
    c, asked = _answering({})
    with pytest.raises(runner.RemoteError, match="Switch to Local"):
        runner._fetch(p["id"], c, job, JobContext(None, lambda: False))
    assert runner.state(p["id"])["phase"] == "failed" and runner.state(p["id"])["job"] == ""
    assert asked == [f"/api/worker/v1/jobs/{job}"]  # deleted there; nothing downloaded
    db.save_settings({"processing_mode": "local"})
    assert runner.decide(p["id"], again=True) == ""  # Process again runs here
    assert (elsewhere / "source.mp4").read_bytes() == b"video"
