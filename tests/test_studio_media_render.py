"""The Find media acceptance example, rendered for real (slow, real FFmpeg; CF2-28/29).

Search for a rain sound and a landscape image, audition both through ClipForge's previews, add them to a project,
place the image between two clips and the rain under the second clip, close and reopen the project, then switch the
provider off and cut the network: the final render uses the local copies, the rain is heard exactly where it was
placed, the image is on screen where it was inserted, and the required credit travels with the render.
"""
from __future__ import annotations

import ipaddress
import subprocess
import time
from pathlib import Path

import httpx
import numpy as np
import pytest

pytestmark = pytest.mark.slow
SR = 48000


def _pcm(path: Path) -> np.ndarray:
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar",
                                   str(SR), "-"])
    return np.frombuffer(raw, dtype=np.float32)


def _band(x: np.ndarray, t0: float, t1: float, freq: float) -> float:
    seg = x[int(t0 * SR):int(t1 * SR)]
    win = np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(seg * win)) * 2 / win.sum()
    bins = np.fft.rfftfreq(len(seg), 1 / SR)
    return float(spec[(bins > freq - 15) & (bins < freq + 15)].max())


def _frame_rgb(path: Path, t: float) -> np.ndarray:
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                                   "-vf", "scale=32:18", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    return np.frombuffer(raw, dtype=np.uint8).reshape(18, 32, 3).astype(float)


def _upload(api, path: Path) -> dict:
    data = path.read_bytes()
    up = api.post("/api/uploads", json={"filename": path.name, "size": len(data)}).json()
    while up["received"] < len(data):
        up = api.put(f"/api/uploads/{up['id']}?offset={up['received']}",
                     content=data[up["received"]:up["received"] + 1_000_000]).json()
    r = api.post(f"/api/uploads/{up['id']}/complete")
    assert r.status_code == 200, r.text
    return r.json()


def _until(fetch, done, timeout=240):
    end = time.time() + timeout
    while time.time() < end:
        v = fetch()
        if done(v):
            return v
        time.sleep(0.3)
    raise AssertionError(f"timed out: {v}")


def test_find_audition_add_place_reopen_and_render_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from clipfoundry import db, netguard
    from clipfoundry.api import app
    from clipfoundry.pipeline import transcribe
    from clipfoundry.studio import media_sources as ms

    def ff(name: str, *args: str) -> Path:
        out = tmp_path / name
        subprocess.run(["ffmpeg", "-y", "-v", "error", *args, str(out)], check=True)
        return out

    # the landscape image is pure red, the rain is a 3 kHz tone, so both can be found in the render
    image = ff("landscape.jpg", "-f", "lavfi", "-i", "color=c=red:s=640x360", "-frames:v", "1", "-update", "1")
    rain = ff("rain.wav", "-f", "lavfi", "-i", "sine=f=3000:d=2:r=48000", "-af", "volume=0.4")
    talk = [ff(f"talk{k}.mp4", "-f", "lavfi", "-i", "color=c=0x224466:s=640x360:r=30:d=4", "-f", "lavfi", "-i",
               f"sine=f={300 + 100 * k}:d=4:r=48000", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
               "-shortest") for k in (1, 2)]
    files = {"live.staticflickr.com/9/landscape.jpg": ("image/jpeg", image.read_bytes()),
             "cdn.freesound.org/previews/9/rain.wav": ("audio/wav", rain.read_bytes())}
    img_item = {"id": "11111111-2222-4333-8444-555555555555", "title": "Wide landscape",
                "foreign_landing_url": "https://www.flickr.com/photos/a/9", "url":
                "https://live.staticflickr.com/9/landscape.jpg", "creator": "Robin", "license": "by",
                "license_version": "4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "source": "flickr", "width": 640, "height": 360, "filetype": "jpg", "mature": False,
                "thumbnail": "https://live.staticflickr.com/9/landscape.jpg"}
    rain_item = {"id": "66666666-7777-4888-8999-000000000000", "title": "Rain shower", "url":
                 "https://cdn.freesound.org/previews/9/rain.wav", "foreign_landing_url": "https://freesound.org/s/9/",
                 "creator": "Ola", "license": "cc0", "license_version": "1.0", "license_url":
                 "https://creativecommons.org/publicdomain/zero/1.0/", "source": "freesound", "duration": 2000,
                 "filesize": len(files["cdn.freesound.org/previews/9/rain.wav"][1]), "filetype": "wav",
                 "category": "sound_effect", "mature": False}

    def web(request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host") or request.url.host
        path = request.url.path
        if host == "api.openverse.org":
            if path == "/v1/images/":
                return httpx.Response(200, json={"results": [img_item]})
            if path == "/v1/audio/":
                return httpx.Response(200, json={"results": [rain_item]})
            for item in (img_item, rain_item):
                if path.endswith(f"/{item['id']}/"):
                    return httpx.Response(200, json=item)
        if host + path in files:
            ctype, body = files[host + path]
            return httpx.Response(200, headers={"content-type": ctype}, content=body)
        return httpx.Response(404)

    monkeypatch.setattr(ms, "transport", httpx.MockTransport(web))
    monkeypatch.setattr(netguard, "resolve", lambda host: [ipaddress.ip_address("93.184.216.34")])
    monkeypatch.setattr(transcribe, "transcribe", lambda wav, duration, *a, **k: {
        "language": "en", "duration": duration, "source": "fixture",
        "segments": [{"start": 0, "end": duration, "text": "", "words": [
            {"start": 0.2, "end": 0.5, "w": "hello"}, {"start": 3.4, "end": 3.7, "w": "there."}]}]})
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        a, b = _upload(api, talk[0]), _upload(api, talk[1])
        r = api.post("/api/studio/videos", json={"name": "Rainy walk", "asset_ids": [a["id"], b["id"]],
                                                 "style_id": "settings",
                                                 "brief": {"aspect_ratio": "16:9", "captions": False,
                                                           "feel": "energetic"}})
        assert r.status_code == 200, r.text
        vid = r.json()["id"]
        v = _until(lambda: api.get(f"/api/studio/videos/{vid}").json(), lambda v: v["plan_revision"] >= 1)
        found_img = api.post("/api/studio/media/search", json={"kind": "image", "query": "landscape",
                                                               "project_id": vid}).json()
        found_rain = api.post("/api/studio/media/search", json={"kind": "effect", "query": "rain",
                                                                "project_id": vid}).json()
        pick_img = next(x for x in found_img["results"] if x["provider"] == "openverse")
        pick_rain = next(x for x in found_rain["results"] if x["provider"] == "openverse")
        assert api.get(pick_img["preview"]["image"]).content == files["live.staticflickr.com/9/landscape.jpg"][1]
        assert api.get(pick_rain["preview"]["audio"]).headers["content-type"] == "audio/wav"
        ids = {}
        for pick in (pick_img, pick_rain):
            imp = api.post("/api/studio/media/imports", json={"result_id": pick["id"], "project_id": vid}).json()
            done = _until(lambda imp=imp: api.get(f"/api/studio/media/imports/{imp['id']}").json(),
                          lambda x: x["status"] in ("ready", "failed"))
            assert done["status"] == "ready", done
            ids[pick["kind"]] = done["asset_id"]
        v = api.get(f"/api/studio/videos/{vid}").json()
        assert ids["image"] in v["bin"] and ids["effect"] in v["bin"]
        r1 = api.post(f"/api/studio/videos/{vid}/edits", json={"base_revision": v["plan_revision"], "edit": {
            "op": "insert", "asset_id": ids["image"], "at": 1, "duration_ms": 2000}}).json()
        second = r1["plan"]["clips"][2]["id"]
        r2 = api.post(f"/api/studio/videos/{vid}/edits", json={"base_revision": r1["plan_revision"], "edit": {
            "op": "add_audio", "asset_id": ids["effect"], "role": "effect", "clip_id": second, "offset_ms": 500,
            "duck": False}})
        assert r2.status_code == 200, r2.text
        rev = r2.json()["plan_revision"]
    # close and reopen; the provider is switched off and the network is gone
    db.save_settings({"media_openverse": False})
    monkeypatch.setattr(ms, "transport", httpx.MockTransport(lambda req: (_ for _ in ()).throw(
        httpx.ConnectError("offline"))))
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        v = api.get(f"/api/studio/videos/{vid}").json()
        assert v["plan_revision"] == rev and v["sources"][ids["image"]][0]["license_name"] == "CC BY 4.0"
        search = api.post("/api/studio/media/search", json={"kind": "image", "query": "x y"}).json()
        assert next(p for p in search["providers"] if p["id"] == "openverse")["state"] == "off"
        r = api.post(f"/api/studio/videos/{vid}/render", json={"revision": rev})
        assert r.status_code == 200, r.text
        v = _until(lambda: api.get(f"/api/studio/videos/{vid}").json(),
                   lambda v: any(x["kind"] == "final" and x["revision"] == rev for x in v["artifacts"]) or
                   any(j["status"] == "failed" and j["kind"] == "video_render" for j in v["jobs"]))
        assert not [j for j in v["jobs"] if j["status"] == "failed"], v["jobs"]
        art = db.select("studio_artifacts", "project_id = ? AND kind = 'final' AND revision = ?", (vid, rev))[0]
        timeline = {s["clip_id"]: s for s in art["info"]["timeline"]}
        img_clip = r2.json()["plan"]["clips"][1]
        assert img_clip["asset_id"] == ids["image"]
        start = timeline[img_clip["id"]]["out_start_ms"] / 1000
        frame = _frame_rgb(Path(art["path"]), start + 1.0)
        assert frame[..., 0].mean() > 180 and frame[..., 1].mean() < 70  # the red landscape is on screen
        placed = [x for x in art["info"]["audio_timeline"] if x["asset_id"] == ids["effect"]]
        assert len(placed) == 1 and placed[0]["out_start_ms"] == timeline[second]["out_start_ms"] + 500
        pcm = _pcm(Path(art["path"]))
        rain_at = placed[0]["out_start_ms"] / 1000
        assert _band(pcm, rain_at + 0.2, rain_at + 1.6, 3000) > 10 * _band(pcm, 0.2, 1.4, 3000)
        assert _band(pcm, rain_at - 1.4, rain_at - 0.1, 3000) * 10 < _band(pcm, rain_at + 0.2, rain_at + 1.6, 3000)
        assert "“Wide landscape” by Robin, CC BY 4.0" in art["info"]["credits"]
        credits_file = Path(art["path"]).parent / "credits.txt"
        assert credits_file.is_file() and "Robin" in credits_file.read_text()
        assert "Rain shower" in api.get(f"/api/studio/videos/{vid}/credits.txt").text
