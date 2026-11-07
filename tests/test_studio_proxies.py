"""Preview proxies (docs/clipforge/LONG_VIDEOS.md, "Proxies for previews"): which videos get one, how it is made and
recorded, the background prepare job, and the engine reading a proxy for previews only, never for a final render,
with the sound still from the original and no piece mixed up between the two. Needs ffmpeg; every render is two
seconds at 360p (one final at full size)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from synthetic_media import make_video, needs_ffmpeg

pytestmark = needs_ffmpeg


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


def _stored(tmp_path: Path, name: str, size: str, seconds: float = 2.0, audio: bool = True) -> dict:
    """A video stored as an upload would be: in a folder of its own under the data folder (its work folder)."""
    from clipfoundry import db
    from clipfoundry.pipeline.ffmpeg_utils import probe

    folder = tmp_path / "data" / "assets" / "local" / f"as-{name}"
    folder.mkdir(parents=True)
    path = make_video(folder / "original.mp4", seconds=seconds, size=size, audio=audio)
    return db.insert("assets", {"id": f"as-{name}", "workspace_id": "local", "kind": "video",
                                "filename": f"{name}.mp4", "sha256": name, "size": path.stat().st_size,
                                "path": str(path), "probe": probe(path)})


def _plan(clips: list[dict], **extra) -> dict:
    from clipfoundry.studio import engine

    return {"schema": engine.SCHEMA, "timebase": 1000, "engine": engine.ENGINE,
            "output": {"aspect": "16:9", "fps": 30}, "layout": "fill", "clips": clips,
            "transition": {"type": "cut", "ms": 0}, "title": {"enabled": False, "text": "", "ms": 2500},
            "captions": {"enabled": False, "style": "clean", "position": "bottom", "size": "medium"},
            "audio": [], "tracks": engine.default_tracks(), "word_fixes": {}, "outline": [], "notes": [], **extra}


def _clip(aid: str, out_ms: int = 2000) -> dict:
    return {"id": f"c-{aid}", "asset_id": aid, "kind": "video", "in_ms": 0, "out_ms": out_ms, "label": aid,
            "gain_db": 0.0, "include": True}


def _loudest(path: Path) -> float:
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar",
                                   "48000", "-"])
    return float(np.abs(np.frombuffer(raw, dtype=np.float32)).max())


def test_big_videos_get_a_proxy_and_small_ones_do_not(env):
    from clipfoundry import db
    from clipfoundry.pipeline.ffmpeg_utils import probe
    from clipfoundry.studio import proxies, uploads

    big = _stored(env, "big", "1400x800")
    small = _stored(env, "small", "640x360")
    assert proxies.wants_proxy(big, {}) and proxies.wants_proxy(big, {"preview_proxies": True})
    assert not proxies.wants_proxy(big, {"preview_proxies": False})  # switched off in Settings
    assert not proxies.wants_proxy(small, {})
    long = {**small, "probe": {**small["probe"], "duration": 601.0}}
    assert proxies.wants_proxy(long, {})  # small but long: a proxy is still worth it
    assert not proxies.wants_proxy({**big, "kind": "image"}, {})

    out = proxies.make_proxy(big)
    assert out == uploads.work_dir(big) / "proxy.mp4" and out.is_file()
    info = probe(out)
    assert info["width"] == 640 and info["height"] == 366 and info["has_audio"]  # 800 * 640 / 1400, made even
    assert info["duration"] == pytest.approx(2.0, abs=0.2) and info["fps"] == pytest.approx(25, abs=0.1)
    row = db.fetch("assets", big["id"])
    assert row["proxy_path"] == str(out) and big["proxy_path"] == str(out)
    assert uploads.asset_view(row)["proxy"] is True and uploads.asset_view(small)["proxy"] is False
    assert not proxies.wants_proxy(row, {})  # already made
    made = out.stat().st_mtime_ns
    assert proxies.make_proxy(row) == out and out.stat().st_mtime_ns == made  # not made again
    assert not list(out.parent.glob("*.tmp.mp4"))

    silent = _stored(env, "silent", "1400x800", audio=False)
    quiet = probe(proxies.make_proxy(silent))
    assert quiet["width"] == 640 and not quiet["has_audio"]


def test_the_prepare_job_makes_sound_transcript_and_proxy(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.pipeline.ffmpeg_utils import FFmpegError
    from clipfoundry.studio import jobs, proxies, uploads, video_flow

    big = _stored(env, "big", "1400x800")
    heard = []
    monkeypatch.setattr(video_flow, "transcript_words",
                        lambda asset, settings, lease=None, cached_only=False: heard.append((asset["id"], lease)) or [])
    job = jobs.enqueue("local", "asset_prepare", big["id"], 0, submit=False)
    lease = jobs.claim(job["id"])
    result = proxies.prepare_job(db.fetch("studio_jobs", job["id"]), lease)
    assert result == {"transcript": False, "proxy": True}  # the stand-in wrote no transcript; the proxy was made
    assert heard == [(big["id"], lease)]
    work = uploads.work_dir(big)
    assert (work / "audio.wav").is_file() and (work / "proxy.mp4").is_file()
    assert jobs.finish(lease, result)
    status = proxies.status(db.fetch("assets", big["id"]))
    assert status == {"transcript": False, "proxy": True,
                      "job": {"id": job["id"], "status": "done", "progress": 1.0, "message": "Done", "error": ""}}
    assert proxies.prepare("local", big["id"]) == {"job": job["id"], "status": "done", "progress": 1.0,
                                                    "message": "Done", "error": ""}  # prepared is prepared

    other = _stored(env, "other", "1400x800")
    monkeypatch.setattr(proxies, "make_proxy", lambda asset, progress=None, cancel=None:
                        (_ for _ in ()).throw(FFmpegError("ffmpeg failed:\nno encoder")))
    job2 = jobs.enqueue("local", "asset_prepare", other["id"], 0, submit=False)
    lease2 = jobs.claim(job2["id"])
    result2 = proxies.prepare_job(db.fetch("studio_jobs", job2["id"]), lease2)  # a proxy failure is not a job failure
    assert result2["transcript"] is False and result2["proxy"] is False
    assert "could not be made" in result2["proxy_error"] and "no encoder" in result2["proxy_error"]
    assert proxies.status(other)["job"]["status"] == "running"

    gone = jobs.enqueue("local", "asset_prepare", "as-gone", 0, submit=False)
    with pytest.raises(ValueError, match="no longer in your media"):
        proxies.prepare_job(db.fetch("studio_jobs", gone["id"]), jobs.claim(gone["id"]))


def test_previews_read_the_proxy_and_finals_never_do(env):
    from clipfoundry import db
    from clipfoundry.studio import engine, proxies, uploads

    big = _stored(env, "big", "1400x800")
    # a silent stand-in proxy: if the preview's sound came from it, the preview would be silent
    make_video(uploads.work_dir(big) / "proxy.mp4", seconds=2.0, size="640x366", audio=False)
    db.update("assets", big["id"], proxy_path=str(uploads.work_dir(big) / "proxy.mp4"))
    assets = {big["id"]: db.fetch("assets", big["id"])}
    plan = _plan([_clip(big["id"])])
    assert engine.validate(plan, assets) == []
    cache = env / "pieces"

    preview = engine.render(plan, assets, {}, env / "p1" / "preview.mp4", preview=True, cache_dir=cache)
    assert preview["proxied"] == [big["id"]] and preview["preview"] and preview["width"] == 640
    assert preview["has_audio"] and preview["audio_timing"]["valid"]
    assert _loudest(env / "p1" / "preview.mp4") > 0.05  # the sound came from the original, not the silent proxy
    from_proxy = {p.name for p in cache.glob("*.h264")}
    assert len(from_proxy) == 1

    plain = engine.render(plan, assets, {}, env / "p2" / "preview.mp4", preview=True,
                          settings={"preview_proxies": False}, cache_dir=cache)
    assert plain["proxied"] == [] and plain["width"] == 640
    from_original = {p.name for p in cache.glob("*.h264")}
    assert len(from_original) == 1 and from_original.isdisjoint(from_proxy)  # another piece, never the proxy's

    final = engine.render(plan, assets, {}, env / "f" / "final.mp4", preview=False, cache_dir=env / "pieces-final")
    assert final["proxied"] == [] and not final["preview"] and final["width"] == 1920 and final["height"] == 1080
    assert _loudest(env / "f" / "final.mp4") > 0.05
    assert "proxy" in engine.capabilities()["notes"]

    # a video overlay's picture comes from the proxy in a preview too (its sound is never used)
    small = _stored(env, "small", "640x360")
    plan2 = _plan([_clip(small["id"])], overlays=[{"id": "o1", "clip_id": f"c-{small['id']}", "asset_id": big["id"],
                                                   "kind": "video", "offset_ms": 200, "length_ms": 1000}])
    assets2 = {**assets, small["id"]: small}
    els, _overlap = engine.frame_map(plan2, 30)
    [ov] = engine._overlay_frames(plan2, els, 30, assets2, True)[0]  # noqa: SLF001
    assert ov["src"] == "proxy" and ov["path"] == assets[big["id"]]["proxy_path"] and ov["asset_id"] == big["id"]
    [ov] = engine._overlay_frames(plan2, els, 30, assets2)[0]  # noqa: SLF001
    assert ov["src"] == "original" and ov["path"] == big["path"]
    assert proxies.wants_proxy(small, {}) is False
