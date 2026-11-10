#!/usr/bin/env python3
"""Checks the local makers (clipfoundry/engines) on a real computer: GitHub's Mac, Windows and Linux test machines.

    python scripts/local_engines_check.py --pins --comfy --graphs --picture flux2-klein-4b --voice --out report.json

--pins     compares every pinned download in catalog.py with its source: the uv wheels with PyPI, ComfyUI's release
           archive by downloading it, and every model file with Hugging Face (size and SHA-256 of the large files from
           the repository at the pinned commit; the small ones are downloaded and hashed). A pin that is still empty
           is reported with the value to write into catalog.py.
--comfy    sets ClipForge's own ComfyUI up exactly as the app does (uv, a private Python, PyTorch for this computer,
           ComfyUI's packages), starts it and runs the two graphs that need no model: a picture and an MP4 clip.
           First it checks that ClipForge reads a folder with letters like é, ü and 東 back from this computer's
           process list (how it recognises a ComfyUI it started).
--graphs   checks that ComfyUI accepts every model graph ClipForge sends (graphs.py): it is given stand-in files with
           the model files' names, so its checks pass and the run then stops where the real file would be loaded.
--picture  downloads one picture model and makes a real 256x256 picture with it (on the processor: slow).
--voice    downloads the built-in voice, says a sentence and checks the sound.

Everything goes into a folder of its own (--data, else a new temporary one); nothing of this computer's ClipForge
is touched. The report (JSON) and what was made go to the folder of --out. Exit code 1 when a check failed or a pin
is missing or wrong.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SMALL = 64 << 20  # files up to this size are downloaded and hashed; larger ones are compared with Hugging Face
HF = "https://huggingface.co"


def log(*parts) -> None:
    print(*parts, flush=True)


# ------------------------------------------------------------------ pins
def _stream_hash(url: str, limit: int | None = None) -> tuple[int, str]:
    import httpx

    h, n = hashlib.sha256(), 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30.0, read=300.0)) as r:
        r.raise_for_status()
        for block in r.iter_bytes(1 << 20):
            n += len(block)
            if limit and n > limit:
                raise RuntimeError(f"{url} is larger than {limit} bytes")
            h.update(block)
    return n, h.hexdigest()


_trees: dict = {}


def _hf_entry(repo: str, revision: str, path: str) -> dict | None:
    import httpx

    folder = path.rpartition("/")[0]
    key = (repo, revision, folder)
    if key not in _trees:
        url = f"{HF}/api/models/{repo}/tree/{revision}" + (f"/{folder}" if folder else "")
        r = httpx.get(url, follow_redirects=True, timeout=60)
        r.raise_for_status()
        _trees[key] = {e["path"]: e for e in r.json() if isinstance(e, dict)}
    return _trees[key].get(path)


def check_pins(report: dict, patch: bool) -> None:
    """Fill report["pins"]; with `patch`, empty pins are replaced (in this run only) by what the source says."""
    import httpx

    from clipfoundry.engines import catalog

    pins: dict = {"uv": {}, "comfyui": {}, "models": {}, "fill": {}, "wrong": []}
    report["pins"] = pins
    # uv: PyPI publishes each wheel's size and SHA-256
    r = httpx.get(f"https://pypi.org/pypi/uv/{catalog.UV_VERSION}/json", timeout=60)
    r.raise_for_status()
    by_name = {u["filename"]: u for u in r.json().get("urls", [])}
    for key, pin in catalog.UV.items():
        u = by_name.get(pin.name) or {}
        ok = (u.get("size") == pin.size and (u.get("digests") or {}).get("sha256") == pin.sha256
              and u.get("url") == pin.url)
        pins["uv"][key] = {"ok": ok, "pypi_size": u.get("size"), "pypi_sha256": (u.get("digests") or {}).get("sha256")}
        if not ok:
            pins["wrong"].append(f"uv {key}")
    # ComfyUI: GitHub's archive of the release tag
    spec = catalog.COMFYUI
    size, sha = _stream_hash(spec["url"], 400 << 20)
    ok = size == spec["size"] and sha == spec["sha256"]
    pins["comfyui"] = {"ok": ok, "size": size, "sha256": sha, "url": spec["url"]}
    if not spec["sha256"]:
        pins["fill"]["COMFYUI"] = {"size": size, "sha256": sha}
        if patch:
            spec.update(size=size, sha256=sha)
    elif not ok:
        pins["wrong"].append("ComfyUI archive")
    # models
    for m in catalog.MODELS:
        rows, new_files = [], []
        for f in m.files:
            entry = _hf_entry(f.repo, f.revision, f.path) or {}
            lfs = entry.get("lfs") or {}
            row = {"path": f.path, "repo": f.repo, "size": f.size, "hf_size": entry.get("size")}
            if lfs:
                row.update(hf_sha256=lfs.get("oid"), ok=entry.get("size") == f.size and lfs.get("oid") == f.sha256)
                got = (int(entry.get("size") or 0), str(lfs.get("oid") or ""))
            elif entry and int(entry.get("size") or 0) <= SMALL:
                got = _stream_hash(catalog.hf_url(f.repo, f.revision, f.path), SMALL)
                row.update(downloaded_sha256=got[1], ok=got == (f.size, f.sha256))
            else:
                got = (0, "")
                row.update(ok=False, problem="not found at the pinned commit" if not entry else "no checksum")
            if not f.sha256 and got[1]:
                pins["fill"][f"{m.id}:{f.path}"] = {"size": got[0], "sha256": got[1]}
                if patch and got[0] == f.size:
                    f = dataclasses.replace(f, sha256=got[1])
            elif not row.get("ok"):
                pins["wrong"].append(f"{m.id}: {f.path}")
            rows.append(row)
            new_files.append(f)
        pins["models"][m.id] = rows
        if patch and tuple(new_files) != m.files:
            _replace_model(dataclasses.replace(m, files=tuple(new_files)))
    log(f"pins: {len(pins['fill'])} to fill, {len(pins['wrong'])} wrong")


def _replace_model(model) -> None:
    from clipfoundry.engines import catalog

    catalog.MODELS = tuple(model if x.id == model.id else x for x in catalog.MODELS)
    for name in dir(catalog):
        if getattr(catalog, name) is not model and getattr(getattr(catalog, name), "id", None) == model.id:
            setattr(catalog, name, model)


def fill_missing(report: dict, want_comfy: bool, model_ids: list[str]) -> None:
    """Without --pins: hash only what this run is about to download and whose pin is still empty."""
    import httpx  # noqa: F401 - needed by the helpers

    from clipfoundry.engines import catalog

    fill = report.setdefault("pins", {}).setdefault("fill", {})
    if want_comfy and not catalog.COMFYUI["sha256"]:
        size, sha = _stream_hash(catalog.COMFYUI["url"], 400 << 20)
        catalog.COMFYUI.update(size=size, sha256=sha)
        fill["COMFYUI"] = {"size": size, "sha256": sha}
    for mid in model_ids:
        m = catalog.by_id(mid)
        if m is None or all(f.sha256 for f in m.files):
            continue
        new = []
        for f in m.files:
            if not f.sha256:
                size, sha = _stream_hash(catalog.hf_url(f.repo, f.revision, f.path), SMALL)
                fill[f"{m.id}:{f.path}"] = {"size": size, "sha256": sha}
                f = dataclasses.replace(f, sha256=sha) if size == f.size else f
            new.append(f)
        _replace_model(dataclasses.replace(m, files=tuple(new)))


# ------------------------------------------------------------------ ComfyUI
def python_traces() -> set[str]:
    """Where uv could put a Python it installs outside ClipForge's folder: python3.12 in the user's bin folder (on
    the PATH) and the Python entries in the Windows registry (PEP 514). The set-up must add none of them."""
    found = set()
    bin_dir = Path(os.environ.get("XDG_BIN_HOME") or Path.home() / ".local" / "bin")
    if bin_dir.is_dir():
        found |= {str(p) for p in bin_dir.iterdir() if p.name.lower().startswith("python3.12")}
    if sys.platform == "win32":
        import winreg

        for hive, hive_name in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
            try:
                with winreg.OpenKey(hive, r"Software\Python") as python_key:
                    for i in range(256):
                        try:
                            company = winreg.EnumKey(python_key, i)
                        except OSError:
                            break
                        with winreg.OpenKey(python_key, company) as company_key:
                            for j in range(256):
                                try:
                                    found.add(rf"{hive_name}\Software\Python\{company}\{winreg.EnumKey(company_key, j)}")
                                except OSError:
                                    break
            except OSError:
                pass
    return found


class Run:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.proc: subprocess.Popen | None = None
        self.base = ""


def setup_comfy(report: dict) -> dict:
    from clipfoundry.engines import catalog, comfy_server, tasks

    flavor = comfy_server.torch_flavor()
    info = {"platform": comfy_server.platform_key(), "flavor": flavor, "torch_label": catalog.TORCH[flavor]["label"]}
    report["comfy"] = info
    problems: list[str] = []
    real_problem = comfy_server.torch_problem

    def lenient(fl, probe):  # GitHub's Mac machines are virtual: Metal is not offered there, so it is only noted
        text = real_problem(fl, probe)
        info["probe"] = probe
        if text and fl == "mps" and not probe.get("mps") and str(probe.get("torch", "")).startswith(catalog.TORCH_VERSION):
            info["mps_note"] = "Metal (MPS) is not available on this test machine; ComfyUI runs on its processor."
            return ""
        if text:
            problems.append(text)
        return text

    comfy_server.torch_problem = lenient
    traces_before = python_traces()
    started = time.time()
    view = tasks.start("Setting up ComfyUI (check)", comfy_server.setup_steps(), wait=True)
    comfy_server.torch_problem = real_problem
    info.update(setup_state=view["state"], setup_error=view.get("error", ""), setup_seconds=round(time.time() - started),
                installed=comfy_server.installed())
    if view["state"] != "done" or not info["installed"]:
        raise RuntimeError(f"setting ComfyUI up failed: {view.get('error') or problems}")
    if (comfy_server.root() / "cache").exists():
        raise RuntimeError("setting ComfyUI up left uv's cache (a second copy of PyTorch) in ClipForge's folder")
    leaked = sorted(python_traces() - traces_before)
    info["python_outside_clipforge"] = leaked
    if leaked:
        raise RuntimeError(f"setting ComfyUI up put its Python outside ClipForge's folder: {leaked}")
    py = str(comfy_server.env_python(flavor))
    out = subprocess.run([py, "-I", "-c", "import json, importlib.metadata as md; print(json.dumps({p: md.version(p) "
                          "for p in ('torch', 'torchvision', 'av', 'transformers', 'comfyui-frontend-package', "
                          "'numpy', 'safetensors', 'sympy', 'pip')}))"], capture_output=True, text=True, timeout=300)
    try:
        info["packages"] = json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        info["packages_error"] = (out.stderr or out.stdout)[-800:]
    root = comfy_server.root()
    info["disk_mb"] = round(sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) / 1e6)
    return info


def start_comfy(run: Run, report: dict, extra: list[str]) -> str:
    from clipfoundry import builtin_ai
    from clipfoundry.engines import comfy_server
    from clipfoundry.engines.comfy import Comfy

    flavor = comfy_server.torch_flavor()
    port = builtin_ai._free_port()  # noqa: SLF001
    cmd = comfy_server.build_command(port, flavor)
    if flavor == "mps" and (report.get("comfy", {}).get("probe") or {}).get("mps") is False:
        cmd.append("--cpu")
    cmd += extra
    report["comfy"]["command"] = cmd[2:]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("HF_", "PYTHONPATH", "VIRTUAL_ENV"))}
    env.update(PYTHONNOUSERSITE="1", HF_HUB_OFFLINE="1", DO_NOT_TRACK="1", PYTHONUTF8="1")
    if flavor == "mps":
        env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    logs = Path(os.environ["CLIPFOUNDRY_DATA"]) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    fh = open(logs / "comfyui.log", "ab")  # noqa: SIM115
    run.proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                cwd=str(comfy_server.main_py().parent), env=env)
    fh.close()
    base = f"http://127.0.0.1:{port}"
    started = time.time()
    while time.time() - started < 900:
        if run.proc.poll() is not None:
            try:  # the reason, in the job log itself
                tail = (logs / "comfyui.log").read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
            except OSError:
                tail = []
            raise RuntimeError(f"ComfyUI stopped while starting (exit {run.proc.returncode}); the end of "
                               "comfyui.log:\n" + "\n".join(tail))
        if Comfy(base, timeout=3).alive():
            break
        time.sleep(1)
    else:
        raise RuntimeError("ComfyUI did not start within 15 minutes")
    stats = Comfy(base, timeout=10).stats()
    report["comfy"]["start_seconds"] = round(time.time() - started, 1)
    report["comfy"]["system_stats"] = stats
    run.base = base
    log(f"ComfyUI is up at {base} after {report['comfy']['start_seconds']} s")
    return base


def stop_comfy(run: Run) -> None:
    if run.proc and run.proc.poll() is None:
        run.proc.terminate()
        try:
            run.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            run.proc.kill()


def _png_info(path: Path) -> dict:
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return {"png": False}
    w, h = struct.unpack(">II", head[16:24])
    info = {"png": True, "width": w, "height": h, "bytes": path.stat().st_size}
    try:
        from PIL import Image, ImageStat

        with Image.open(path) as im:
            stat = ImageStat.Stat(im.convert("RGB"))
            info["mean"] = [round(x, 1) for x in stat.mean]
            info["stddev"] = [round(x, 1) for x in stat.stddev]
            import numpy as np

            g = np.asarray(im.convert("L"), dtype=np.float64)
            if g.shape[1] > 1 and g.std() > 0:
                # neighbouring pixels of a real picture are alike (about 0.8 to 1); in noise they are not (about 0)
                info["smooth"] = round(float(np.corrcoef(g[:, :-1].ravel(), g[:, 1:].ravel())[0, 1]), 3)
    except Exception as exc:  # noqa: BLE001
        info["pixels_error"] = str(exc)[:200]
    return info


def _preview(path: Path) -> str:
    """A small JPEG of the picture as base64, printed into the job log so it can be looked at without the artifact."""
    import base64
    import io

    from PIL import Image

    with Image.open(path) as im:
        small = im.convert("RGB")
        small.thumbnail((128, 128))
        buf = io.BytesIO()
        small.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _mp4_info(path: Path) -> dict:
    data = path.read_bytes()
    info = {"bytes": len(data), "ftyp": data[4:8] == b"ftyp", "brand": data[8:12].decode("latin-1")}
    probe = shutil.which("ffprobe")
    if probe:
        out = subprocess.run([probe, "-v", "error", "-show_entries", "stream=codec_name,width,height,nb_frames,r_frame_rate",
                              "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
        try:
            info["streams"] = json.loads(out.stdout).get("streams")
        except ValueError:
            pass
    return info


def model_free_graphs(run: Run, report: dict) -> None:
    from clipfoundry.engines import graphs
    from clipfoundry.engines.comfy import Comfy

    res: dict = {}
    report["model_free"] = res
    client = Comfy(run.base, timeout=60)
    for name, (graph, _node) in (("picture", graphs.check_picture()), ("video", graphs.check_video())):
        started, seen = time.time(), []
        files = client.run(graph, progress=lambda f, m, s=seen: s.append(m), timeout_s=900)
        dest = run.out / f"model-free-{name}{Path(files[-1]['filename']).suffix}"
        client.download(files[-1], dest)
        res[name] = {"seconds": round(time.time() - started, 1), "files": files, "progress": seen[-5:],
                     "result": _png_info(dest) if name == "picture" else _mp4_info(dest)}
        log(f"model-free {name}: {res[name]['result']}")
    ok_pic = res["picture"]["result"].get("png") and res["picture"]["result"].get("width") == 256
    ok_vid = res["video"]["result"].get("ftyp") and res["video"]["result"]["bytes"] > 1000
    if not (ok_pic and ok_vid):
        raise RuntimeError(f"a model-free graph made the wrong thing: {res}")


def model_graphs(run: Run, report: dict) -> None:
    """Every model graph passes ComfyUI's checks with stand-in files and fails only where a file is loaded."""
    from clipfoundry.engines import catalog, comfy_server, graphs
    from clipfoundry.engines.comfy import Comfy, _entry_error

    res: dict = {}
    report["model_graphs"] = res
    client = Comfy(run.base, timeout=60)
    made: list[Path] = []
    for m in catalog.MODELS:
        if m.role == "voice":
            continue
        for f in m.files:
            p = comfy_server.models_root() / f.folder / f.name
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"not a model: a stand-in for the graph check")
                made.append(p)
    start_png = run.out / "model-free-picture.png"
    try:
        for m in catalog.MODELS:
            if m.role == "voice":
                continue
            cases = []
            if m.role == "image":
                w, h = graphs.picture_size(m, 768, 1344)
                cases.append(("words", graphs.picture(m, "a red bicycle by a canal", "blurry", w, h, 7)))
            else:
                w, h, frames, fps = graphs.video_shape(m, 480, 832, 2.0)
                cases.append(("words", graphs.video(m, "waves rolling onto a beach", "", w, h, frames, fps, 7)))
                if start_png.is_file():
                    name = client.upload_image(start_png)
                    cases.append(("picture", graphs.video(m, "the picture comes alive", "", w, h, frames, fps, 7,
                                                          name)))
            for label, (graph, steps_node) in cases:
                row: dict = {"nodes": graphs.class_types(graph), "missing_nodes": client.missing_nodes(
                    graphs.class_types(graph))}
                r = client._post("/prompt", {"prompt": graph, "client_id": client.client_id})  # noqa: SLF001
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                row["status"] = r.status_code
                row["node_errors"] = body.get("node_errors") or {}
                row["error"] = body.get("error")
                pid = body.get("prompt_id")
                if pid:
                    deadline = time.time() + 600
                    entry = None
                    while time.time() < deadline:
                        entry = client.history(pid)
                        if entry:
                            break
                        time.sleep(1)
                    msgs = ((entry or {}).get("status") or {}).get("messages") or []
                    failed = next((d for k, d in msgs if k == "execution_error"), None)
                    row["ran"] = bool(entry)
                    if failed:
                        node = str(failed.get("node_id"))
                        row["failed_at"] = {"node": node, "class_type": graph.get(node, {}).get("class_type"),
                                            "error": str(failed.get("exception_message") or "")[:300]}
                    row["error_text"] = _entry_error(entry or {})[:300]
                loader = (row.get("failed_at") or {}).get("class_type") in ("UNETLoader", "CLIPLoader", "VAELoader")
                row["ok"] = r.status_code == 200 and not row["node_errors"] and not row["missing_nodes"] and loader
                res[f"{m.id}:{label}"] = row
                log(f"graph {m.id} ({label}): ok={row['ok']} failed_at={row.get('failed_at')}")
    finally:
        for p in made:
            p.unlink(missing_ok=True)
    bad = [k for k, v in res.items() if not v["ok"]]
    if bad:
        raise RuntimeError(f"ComfyUI did not take these graphs: {bad}")


def real_picture(run: Run, report: dict, model_id: str) -> None:
    from clipfoundry.engines import catalog, graphs, models, tasks
    from clipfoundry.engines.comfy import Comfy

    m = catalog.by_id(model_id)
    if m is None or m.role != "image":
        raise RuntimeError(f"no picture model {model_id!r}")
    res: dict = {"model": m.id, "download_gb": round(m.bytes / 1e9, 2)}
    report["picture"] = res
    started = time.time()
    view = tasks.start(f"Downloading {m.name} (check)", models.install_steps(m, "clipforge", None), wait=True)
    res.update(download_state=view["state"], download_error=view.get("error", ""),
               download_seconds=round(time.time() - started))
    if view["state"] != "done" or models.missing(m, "clipforge", None):
        raise RuntimeError(f"downloading {m.name} failed: {view.get('error')}")
    graph, steps_node = graphs.picture(m, "A red bicycle leaning on a stone wall by a canal, morning light, photo",
                                       "", 256, 256, 7)
    seen: list[tuple[float, str]] = []
    started = time.time()
    files = Comfy(run.base, timeout=120).run(graph, progress=lambda f, msg: seen.append((round(f, 3), msg)),
                                             timeout_s=3600, steps_node=steps_node, labels=graphs.labels(graph))
    dest = run.out / f"picture-{m.id}.png"
    Comfy(run.base, timeout=120).download(files[-1], dest)
    res.update(seconds=round(time.time() - started, 1), progress=seen[-8:], result=_png_info(dest))
    log(f"real picture: {res['result']} in {res['seconds']} s")
    try:
        log(f"PREVIEW-JPEG-BASE64 {_preview(dest)}")
    except Exception as exc:  # noqa: BLE001 - the preview is a convenience
        log(f"no preview: {exc}")
    px = res["result"]
    if not (px.get("png") and px.get("width") == 256 and px.get("height") == 256 and max(px.get("stddev") or [0]) > 8
            and (px.get("smooth") or 0) >= 0.5):
        raise RuntimeError(f"the picture is not right (flat, noise or wrong size): {px}")


def check_voice(report: dict, out: Path) -> None:
    import wave

    from clipfoundry.engines import tasks, voice

    res: dict = {}
    report["voice"] = res
    started = time.time()
    view = tasks.start("Downloading the voice (check)", voice.install_steps(), wait=True)
    res.update(download_state=view["state"], download_error=view.get("error", ""),
               download_seconds=round(time.time() - started, 1), installed=voice.installed())
    if not voice.installed():
        raise RuntimeError(f"downloading the voice failed: {view.get('error')}")
    text = ("Here's the thing nobody tells you about starting out. The first step is the hardest, and it's also the "
            "one that matters most.")
    for v in ("F1", "M2"):
        started = time.time()
        got = voice.speak(text, voice=v)
        seconds = time.time() - started
        path = Path(got["path"])
        with wave.open(str(path)) as w:
            frames, rate = w.getnframes(), w.getframerate()
            raw = w.readframes(frames)
        import numpy as np

        pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(pcm ** 2))) if pcm.size else 0.0
        words = got["words"]
        ordered = all(a["start_s"] <= b["start_s"] and a["end_s"] <= b["end_s"] + 1e-6 for a, b in zip(words, words[1:]))
        row = {"seconds_taken": round(seconds, 2), "duration_s": got["duration_s"], "sample_rate": rate,
               "rms": round(rms, 4), "words": len(words), "words_in_order": ordered,
               "realtime_factor": round(got["duration_s"] / max(0.01, seconds), 1)}
        res[v] = row
        shutil.copy2(path, out / f"voice-{v}.wav")
        log(f"voice {v}: {row}")
        if not (4.0 < got["duration_s"] < 20.0 and rms > 0.01 and ordered and len(words) == len(text.split())):
            raise RuntimeError(f"the voice {v} does not sound right: {row}")



# ------------------------------------------------------------------ recognising ClipForge's own ComfyUI
def check_process_names(report: dict) -> None:
    """ClipForge recognises a ComfyUI it started (left over from an earlier run, or shared by two ClipForge windows) by
    ClipForge's folder in its command line, and that folder can hold any letters (C:\\Users\\José). A stand-in
    process with such a folder in its command line must be read back exactly, here without LANG (a Mac app opened
    from the Finder has none)."""
    from clipfoundry.engines import comfy_server

    folder = str(Path(tempfile.gettempdir()) / "ClipForge José Müller Øre 東京" / "main.py")
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)", folder],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    bare = {k: os.environ.pop(k) for k in list(os.environ) if k == "LANG" or k.startswith("LC_")}
    try:
        line = ""
        for _ in range(40):  # Windows lists a new process a moment after it starts
            line = comfy_server._cmdline(proc.pid)  # noqa: SLF001
            if folder in line:
                break
            time.sleep(0.5)
        row = {"read": line.strip()[-200:], "ok": folder in line}
        if sys.platform == "darwin":  # for the record: what ps writes when it is not asked for UTF-8
            plain = subprocess.run(["/bin/ps", "-p", str(proc.pid), "-o", "command="], capture_output=True, timeout=10)
            row["plain_ps"] = plain.stdout.decode("utf-8", "replace").strip()[-200:]
        report["process_names"] = row
        log(f"process names: {row}")
        if not row["ok"]:
            raise RuntimeError(f"ClipForge read its folder wrongly from this computer's process list: {line!r}")
    finally:
        os.environ.update(bare)
        proc.kill()
        proc.wait()


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="", help="the folder to work in (default: a new temporary one)")
    ap.add_argument("--out", default="local-engines-check.json")
    ap.add_argument("--pins", action="store_true")
    ap.add_argument("--comfy", action="store_true")
    ap.add_argument("--graphs", action="store_true")
    ap.add_argument("--picture", default="")
    ap.add_argument("--voice", action="store_true")
    args = ap.parse_args()

    data = Path(args.data) if args.data else Path(tempfile.mkdtemp(prefix="clipforge-engines-check-"))
    data.mkdir(parents=True, exist_ok=True)
    os.environ["CLIPFOUNDRY_DATA"] = str(data)
    os.environ.pop("CLIPFOUNDRY_MODE", None)
    out_file = Path(args.out).resolve()
    out = out_file.parent / "made"
    out.mkdir(parents=True, exist_ok=True)

    report: dict = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "python": sys.version.split()[0],
                    "system": f"{platform.system()} {platform.release()} {platform.machine()}", "data": str(data),
                    "failed": []}
    try:
        from clipfoundry.builtin_ai import memory_mb

        report["memory_mb"] = memory_mb()
    except Exception:  # noqa: BLE001
        pass
    report["free_disk_gb"] = round(shutil.disk_usage(data).free / 1e9, 1)

    def step(name: str, fn, *a) -> bool:
        log(f"== {name}")
        started = time.time()
        try:
            fn(*a)
            return True
        except Exception as exc:  # noqa: BLE001 - every check is reported
            report["failed"].append({"check": name, "error": f"{exc.__class__.__name__}: {exc}"[:2000],
                                     "trace": traceback.format_exc()[-3000:]})
            log(f"!! {name} failed: {exc}")
            return False
        finally:
            report.setdefault("times", {})[name] = round(time.time() - started, 1)

    if args.pins:
        step("pins", check_pins, report, True)
    else:
        step("pins (only what this run downloads)", fill_missing, report, args.comfy,
             ([args.picture] if args.picture else []) + (["supertonic-3"] if args.voice else []))
    run = Run(out)
    try:
        if args.comfy:
            step("ClipForge's folder read back from the process list", check_process_names, report)
        if args.comfy and step("set ComfyUI up", setup_comfy, report):
            extra = []
            from clipfoundry.engines import comfy_server

            if args.picture and comfy_server.torch_flavor() != "cuda":
                extra.append("--bf16-unet")  # the test machines have 16 GB: the model stays in bf16 on the processor
            if step("start ComfyUI", start_comfy, run, report, extra):
                step("graphs without a model", model_free_graphs, run, report)
                if args.graphs:
                    step("model graphs", model_graphs, run, report)
                if args.picture:
                    step("a real picture", real_picture, run, report, args.picture)
        if args.voice:
            step("the voice", check_voice, report, out)
    finally:
        stop_comfy(run)
        logs = data / "logs"
        for f in logs.glob("*.log") if logs.is_dir() else []:
            shutil.copy2(f, out / f.name)

    pins = report.get("pins") or {}
    if pins.get("fill"):
        report["failed"].append({"check": "pins", "error": "pins to write into catalog.py: "
                                 + json.dumps(pins["fill"], indent=1)})
    if pins.get("wrong"):
        report["failed"].append({"check": "pins", "error": f"pins that do not match their source: {pins['wrong']}"})
    report["ok"] = not report["failed"]
    out_file.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = [f"## Local makers on {report['system']}", "", f"**{'All checks passed' if report['ok'] else 'Problems'}**",
             ""]
    lines += [f"- {k}: {v} s" for k, v in report.get("times", {}).items()]
    for f in report["failed"]:
        lines += ["", f"### {f['check']}", "```", f["error"][:3000], "```"]
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    log("\n".join(lines))
    if pins.get("fill"):
        log("PINS-TO-FILL " + json.dumps(pins["fill"], sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
