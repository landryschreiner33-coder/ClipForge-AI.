"""Check the built-in AI and the sound cleanup on a real computer (run by .github/workflows/builtin-ai-check.yml).

1. The pinned catalog still matches its sources: each model file's size and SHA-256 at its pinned Hugging Face
   revision, and each engine archive's size and SHA-256 on the llama.cpp release.
2. This computer's engine and the Basic level (and Standard with --standard) download, verify and start.
3. Speed: how long the model takes to load, and words per second for a clip-scoring answer that must be JSON; a
   picture question checks that the vision part loaded too.
4. Sound cleanup (--sound): the voice model downloads and verifies, and how fast a minute of speech is cleaned.
5. The meaning model (--meaning, clipfoundry/embedder.py): the pinned files download and verify, paraphrases end
   up closer than strangers, and how many sentences a second it embeds.
6. The eyes (--eyes, with a level): the model answers a JSON-schema question about three frames of a small test
   video through the app's own eyes.look, and a schema-bound ranking question through builtin_ai.chat.

Writes a JSON report (--out) and, on GitHub, a summary table. Exits 1 when anything does not match or fails.
Everything goes into a fresh data folder (--data), never the user's own.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCORING = ("Rate this short video clip for how likely it is to hold viewers on TikTok and YouTube Shorts. Answer "
           "only with JSON: {\"score\": 0-100, \"hook\": \"a better first line, at most 12 words\", \"reason\": "
           "\"one sentence\"}.\n\nTranscript: \"Most people quit the gym in three weeks. Here's the one change that "
           "kept me going for five years. I stopped planning workouts and started planning the walk to the gym. "
           "Put your shoes by the door the night before. That's it. The rest takes care of itself.\"")


def png(width: int = 64, height: int = 64, rgb: tuple[int, int, int] = (220, 20, 20)) -> bytes:
    """A plain one-colour PNG, written without any imaging library."""
    row = b"\x00" + bytes(rgb) * width
    raw = row * height

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def check_catalog(builtin_ai, httpx) -> list[str]:
    """Problems with the pinned catalog (empty when everything matches its source)."""
    problems = []
    for level, spec in builtin_ai.MODELS.items():
        url = f"https://huggingface.co/api/models/{spec['repo']}/tree/{spec['revision']}"
        r = httpx.get(url, timeout=60, follow_redirects=True)
        if r.status_code != 200:
            problems.append(f"{level}: {url} answered {r.status_code}")
            continue
        listed = {e["path"]: e for e in r.json()}
        for f in spec["files"]:
            e = listed.get(f["name"])
            if not e:
                problems.append(f"{level}: {f['name']} is not in {spec['repo']}@{spec['revision']}")
                continue
            lfs = e.get("lfs") or {}
            if int(lfs.get("size") or e.get("size") or 0) != f["size"] or lfs.get("oid") != f["sha256"]:
                problems.append(f"{level}: {f['name']} is {lfs.get('size')} bytes, sha256 {lfs.get('oid')}; "
                                f"the catalog says {f['size']} and {f['sha256']}")
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    url = f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{builtin_ai.ENGINE_VERSION}"
    r = httpx.get(url, headers=headers, timeout=60)
    if r.status_code != 200:
        problems.append(f"engine: {url} answered {r.status_code}")
    else:
        assets = {a["name"]: a for a in r.json().get("assets") or []}
        for key, spec in builtin_ai.ENGINES.items():
            a = assets.get(spec["file"])
            if not a:
                problems.append(f"engine {key}: {spec['file']} is not in release {builtin_ai.ENGINE_VERSION}")
                continue
            digest = str(a.get("digest") or "")
            if int(a["size"]) != spec["size"] or (digest and digest != f"sha256:{spec['sha256']}"):
                problems.append(f"engine {key}: {spec['file']} is {a['size']} bytes, {digest or 'no digest'}; "
                                f"the catalog says {spec['size']} and sha256:{spec['sha256']}")
    return problems


def ask(httpx, base: str, key: str, messages: list, **extra) -> tuple[str, dict, float]:
    t0 = time.monotonic()
    r = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"}, timeout=600,
                   trust_env=False, json={"model": "clipforge-builtin", "temperature": 0.2, "messages": messages,
                                          **extra})
    elapsed = time.monotonic() - t0
    r.raise_for_status()
    body = r.json()
    return body["choices"][0]["message"]["content"] or "", body, elapsed


def check_level(builtin_ai, httpx, level: str, report: dict) -> list[str]:
    problems = []
    row: dict = {"level": level, "model": builtin_ai.MODELS[level]["model"]}
    report["levels"].append(row)
    t0 = time.monotonic()
    last = [0.0]

    def progress(status: str, done: int, total: int) -> None:
        if time.monotonic() - last[0] > 30:
            last[0] = time.monotonic()
            print(f"  {status}: {done / 1e6:.0f} of {total / 1e6:.0f} MB", flush=True)

    builtin_ai._install_engine(progress)  # noqa: SLF001 - the same code the app runs, without its thread
    builtin_ai._install_level(level, progress)  # noqa: SLF001
    row["download_and_check_s"] = round(time.monotonic() - t0, 1)
    settings = {"ai_provider": "builtin", "builtin_ai_level": level, "builtin_ai_idle_minutes": 30}
    t0 = time.monotonic()
    try:
        base, key = builtin_ai.server.ensure(settings)
    except builtin_ai.BuiltinError as exc:
        log = Path(os.environ["CLIPFOUNDRY_DATA"]) / "logs" / "builtin-ai.log"
        tail = log.read_text(errors="replace")[-3000:] if log.exists() else ""
        return [f"{level}: the engine did not start: {exc}\n{tail}"]
    row["load_s"] = round(time.monotonic() - t0, 1)
    try:
        for attempt in ("cold", "warm"):
            text, body, elapsed = ask(httpx, base, key, [{"role": "user", "content": SCORING}],
                                      response_format={"type": "json_object"}, max_tokens=200)
            timings = body.get("timings") or {}
            usage = body.get("usage") or {}
            row[f"{attempt}_answer_s"] = round(elapsed, 2)
            row[f"{attempt}_tokens_per_s"] = round(float(timings.get("predicted_per_second") or (
                (usage.get("completion_tokens") or 0) / max(elapsed, 1e-6))), 1)
            row["prompt_tokens_per_s"] = round(float(timings.get("prompt_per_second") or 0), 1)
            try:
                answer = json.loads(text)
                if not (isinstance(answer, dict) and isinstance(answer.get("score"), (int, float))):
                    raise ValueError("no score")
                row["answer"] = answer
            except ValueError:
                problems.append(f"{level}: the scoring answer was not the asked-for JSON: {text[:300]!r}")
        picture = "data:image/png;base64," + base64.b64encode(png()).decode()
        text, _body, elapsed = ask(httpx, base, key, [{"role": "user", "content": [
            {"type": "text", "text": "What colour fills this picture? Answer with one word."},
            {"type": "image_url", "image_url": {"url": picture}}]}], max_tokens=10)
        row["vision_answer"], row["vision_s"] = text.strip(), round(elapsed, 2)
        if "red" not in text.lower():
            problems.append(f"{level}: the picture question was answered {text!r} (expected red)")
        # the app's own entry point, as Autopilot and the editor call it
        reply = builtin_ai.chat(settings, "Answer with one word.", "Say OK.")
        row["chat_ok"] = bool(reply.strip())
    except Exception as exc:  # noqa: BLE001 - report every failure, then stop the engine
        problems.append(f"{level}: {type(exc).__name__}: {exc}")
    finally:
        builtin_ai.server.stop()
    row["stopped"] = not builtin_ai.server.running()
    return problems


def speech(seconds: float, folder: Path):
    """About `seconds` of synthesized speech with room noise and hum, and word timings from its clean voice."""
    import numpy as np

    sr = 48000
    lines = ["Today I want to show you how this works.", "First, open the settings and pick a style.",
             "Then press render and wait a moment.", "The clip comes out clean and ready to post.",
             "That is really all there is to it.", "Thanks for watching, see you next time."]
    parts, words, t, k = [], [], 0.0, 0
    while t < seconds:
        line = lines[k % len(lines)]
        wav = folder / f"line{k}.wav"
        if sys.platform == "darwin":
            subprocess.run(["say", "-o", str(wav.with_suffix(".aiff")), line], check=True)
            src = wav.with_suffix(".aiff")
        elif shutil.which("espeak-ng"):
            subprocess.run(["espeak-ng", "-w", str(wav), line], check=True)
            src = wav
        else:
            return None
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
                             capture_output=True, check=True).stdout
        v = np.frombuffer(raw, np.float32).astype(np.float64)
        v = v / (np.abs(v).max() + 1e-9) * (0.5 if k % 2 else 0.15)
        env = np.sqrt(np.convolve(v ** 2, np.ones(960) / 960, "same"))
        on = env > 0.02 * np.abs(v).max()
        edges = np.flatnonzero(np.diff(np.concatenate([[0], on.astype(int), [0]])))
        for a, b in zip(edges[::2], edges[1::2]):
            if b - a > 0.05 * sr:
                words.append({"w": "x", "start": t + a / sr, "end": t + b / sr})
        parts += [v, np.zeros(int(0.8 * sr))]
        t += v.size / sr + 0.8
        k += 1
    x = np.concatenate(parts)
    rng = np.random.default_rng(0)
    tt = np.arange(x.size) / sr
    x = x + 0.006 * rng.standard_normal(x.size) + 0.004 * np.sin(2 * np.pi * 60 * tt)
    out = folder / "speech.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
                    str(out)], input=x.astype(np.float32).tobytes(), check=True)
    return out, x.size / sr, words


def check_meaning(report: dict) -> list[str]:
    """The meaning model: pinned download, checksums, sensible similarities, speed."""
    from clipfoundry import embedder
    from clipfoundry.pipeline import semantic

    row: dict = {"model": embedder.MODEL, "download_mb": round(embedder.download_bytes() / 1e6, 1)}
    report["meaning"] = row
    t0 = time.monotonic()
    try:
        embedder.ensure_model()
    except embedder.MeaningError as exc:
        return [f"meaning: the model could not be downloaded and verified: {exc}"]
    row["download_and_check_s"] = round(time.monotonic() - t0, 1)
    if not embedder.runtime_ok():
        return ["meaning: onnxruntime is not installed, so the model cannot be loaded"]
    t0 = time.monotonic()
    texts = ["The cat sat on the mat.", "A kitten rested on the rug.", "Quarterly tax returns are due in April.",
             "Boil the pasta in plenty of salted water."]
    emb = semantic.embed_texts(texts, opts={"meaning_model": True})
    row["load_and_first_s"] = round(time.monotonic() - t0, 2)
    problems = []
    if emb.model != embedder.MODEL:
        return [f"meaning: the vectors came from {emb.model!r}, not the meaning model"]
    same = semantic.cos_cal(emb, emb[0], emb[1])
    other = max(semantic.cos_cal(emb, emb[0], emb[2]), semantic.cos_cal(emb, emb[0], emb[3]),
                semantic.cos_cal(emb, emb[1], emb[3]))
    row.update(paraphrase=round(same, 3), strangers=round(other, 3), baseline=round(emb.baseline, 3))
    if not (same > 0.4 and same > other + 0.2):
        problems.append(f"meaning: paraphrases scored {same:.2f} and strangers {other:.2f}; the model is not behaving")
    many = [f"Sentence number {k} talks about {w} and a few other things." for k, w in
            enumerate(["cats", "taxes", "pasta", "rain", "music", "cars", "sleep", "coffee", "maps", "shoes"] * 20)]
    t0 = time.monotonic()
    embedder.embed(many, {"meaning_model": True})
    took = time.monotonic() - t0
    row.update(sentences=len(many), embed_s=round(took, 2), sentences_per_s=round(len(many) / max(took, 1e-6), 1))
    if took > 120:
        problems.append(f"meaning: {len(many)} sentences took {took:.0f} s; too slow to be useful")
    return problems


def check_eyes(builtin_ai, level: str, report: dict) -> list[str]:
    """The eyes and the schema-bound answers, through the app's own code paths (needs ffmpeg for the test video)."""
    from clipfoundry.pipeline import eyes, scout

    row: dict = {"level": level}
    report["eyes"] = row
    settings = {"ai_provider": "builtin", "builtin_ai_level": level, "builtin_ai_idle_minutes": 30,
                "ai_edit_timeout_s": 120}
    problems = []
    try:
        builtin_ai._install_engine(lambda *a: None)  # noqa: SLF001 - already present after check_level
        builtin_ai._install_level(level, lambda *a: None)  # noqa: SLF001
        t0 = time.monotonic()
        text = builtin_ai.chat(settings, scout.SYSTEM, 'Two finalists: 1 "Stop doing this with your key light." and '
                               '2 "Hi everyone, welcome back to the channel." Rank them, best first, with a verdict each.',
                               json_schema=scout.JUDGE_SCHEMA, json_object=True, max_tokens=300, timeout=600)
        row["schema_answer"], row["schema_s"] = text[:300], round(time.monotonic() - t0, 2)
        data = json.loads(text)
        if not (isinstance(data.get("ranking"), list) and data["ranking"] and int(data["ranking"][0]) == 1):
            problems.append(f"eyes: the schema-bound ranking was {text[:200]!r} (expected finalist 1 first)")
        if not shutil.which("ffmpeg"):
            row["frames"] = "no ffmpeg on this computer: the picture question was skipped"
            return problems
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "test.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=red:s=320x568:r=25:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
                           check=True)
            t0 = time.monotonic()
            seen = eyes.look(str(video), 0.0, 3.0, "a plain red test picture", settings, None, deadline=time.monotonic() + 600)
        row["look_s"] = round(time.monotonic() - t0, 2)
        row["seen"] = seen
        if not seen:
            problems.append("eyes: eyes.look returned nothing for the test video")
        elif seen["kind"] not in eyes.KINDS or not 1 <= seen["appeal"] <= 10:
            problems.append(f"eyes: an answer outside the schema: {seen}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"eyes: {type(exc).__name__}: {exc}")
    finally:
        builtin_ai.server.stop()
    return problems


def check_sound(report: dict) -> list[str]:
    from clipfoundry.pipeline import cleanup

    row: dict = {}
    report["sound"] = row
    t0 = time.monotonic()
    try:
        cleanup.ensure_model()
    except cleanup.CleanupError as exc:
        return [f"sound: the voice model could not be downloaded and verified: {exc}"]
    row["model_download_s"] = round(time.monotonic() - t0, 1)
    if cleanup.denoiser_kind() != "deepfilternet":
        return ["sound: the voice model was downloaded but could not be loaded (is onnxruntime installed?)"]
    with tempfile.TemporaryDirectory() as tmp:
        made = speech(60, Path(tmp))
        if made is None:
            return ["sound: no speech synthesizer (say or espeak-ng) on this computer"]
        src, seconds, words = made
        t0 = time.monotonic()
        result = cleanup.clean(src, 0.0, seconds, words, "gentle")
        took = time.monotonic() - t0
    rep = result.report
    row.update(seconds_of_sound=round(seconds, 1), cleaning_s=round(took, 1), realtime_factor=round(took / seconds, 3),
               denoiser=rep.get("denoiser"), summary=rep.get("summary"),
               noise_below_voice_db=[rep.get("noise_below_voice_db_before"), rep.get("noise_below_voice_db_after")])
    problems = []
    if rep.get("denoiser") != "deepfilternet":
        problems.append(f"sound: cleaned with {rep.get('denoiser')}, not the voice model")
    if (rep.get("noise_below_voice_db_after") or 0) < (rep.get("noise_below_voice_db_before") or 0) + 5:
        problems.append(f"sound: background noise was not lowered enough: {rep.get('summary')}")
    return problems


def summary_table(report: dict) -> str:
    c = report["computer"]
    lines = [f"### Built-in AI check: {c['platform']} ({c['memory_mb'] / 1024:.0f} GB memory, "
             f"recommended level {c['recommended']})", ""]
    if report["levels"]:
        lines += ["| Level | Download + check | Load | Answer (warm) | Words/s (warm) | Picture | JSON |",
                  "|---|---|---|---|---|---|---|"]
        for r in report["levels"]:
            lines.append(f"| {r['level']} ({r['model']}) | {r.get('download_and_check_s', '-')} s | "
                         f"{r.get('load_s', '-')} s | {r.get('warm_answer_s', '-')} s | "
                         f"{r.get('warm_tokens_per_s', '-')} tokens/s | {r.get('vision_answer', '-')} | "
                         f"{'yes' if r.get('answer') else 'no'} |")
    s = report.get("sound")
    if s:
        lines += ["", f"Sound cleanup: {s.get('seconds_of_sound')} s of speech cleaned in {s.get('cleaning_s')} s "
                      f"(real-time factor {s.get('realtime_factor')}), {s.get('summary')}"]
    m = report.get("meaning")
    if m:
        lines += ["", f"Meaning model: {m.get('download_mb')} MB downloaded and checked in {m.get('download_and_check_s')} s; "
                      f"paraphrase {m.get('paraphrase')} vs strangers {m.get('strangers')}; "
                      f"{m.get('sentences_per_s')} sentences/s"]
    e = report.get("eyes")
    if e:
        lines += ["", f"Eyes ({e.get('level')}): schema ranking in {e.get('schema_s')} s; "
                      f"picture: {json.dumps(e.get('seen'))[:200]} in {e.get('look_s')} s"]
    if not report.get("catalog_checked"):
        lines += ["", "Catalog: not checked on this machine (the Linux job checks it)"]
    else:
        lines += ["", "Catalog: " + ("matches its sources" if not report["catalog_problems"] else
                                     "; ".join(report["catalog_problems"]))]
    if report["problems"]:
        lines += ["", "**Problems:**", *[f"- {p}" for p in report["problems"]]]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", help="data folder to use (default: a new temporary folder)")
    ap.add_argument("--out", default="builtin-ai-check.json")
    ap.add_argument("--standard", action="store_true", help="also check the Standard level (about 5 GB)")
    ap.add_argument("--sound", action="store_true", help="also check the sound cleanup's voice model and speed")
    ap.add_argument("--meaning", action="store_true", help="also check the meaning model (a 90 MB download)")
    ap.add_argument("--eyes", action="store_true", help="also check the eyes and schema-bound answers (Basic level)")
    ap.add_argument("--no-catalog", action="store_true")
    args = ap.parse_args()
    os.environ["CLIPFOUNDRY_DATA"] = args.data or tempfile.mkdtemp(prefix="clipforge-ai-check-")
    import httpx

    from clipfoundry import builtin_ai

    mem, gpu = builtin_ai.memory_mb(), builtin_ai.vram_mb()
    report: dict = {"computer": {"platform": f"{platform.system()} {platform.machine()}", "key": builtin_ai.platform_key(),
                                 "memory_mb": mem, "vram_mb": gpu, "cpus": os.cpu_count(),
                                 "recommended": builtin_ai.recommended_level(mem, gpu, sys.platform == "darwin")},
                    "levels": [], "catalog_checked": not args.no_catalog, "catalog_problems": [], "problems": []}
    print(json.dumps(report["computer"]), flush=True)
    if not args.no_catalog:
        report["catalog_problems"] = check_catalog(builtin_ai, httpx)
        report["problems"] += report["catalog_problems"]
    for level in ("basic", "standard") if args.standard else ("basic",):
        print(f"checking the {level} level", flush=True)
        try:
            report["problems"] += check_level(builtin_ai, httpx, level, report)
        except Exception as exc:  # noqa: BLE001
            report["problems"].append(f"{level}: {type(exc).__name__}: {exc}")
        if args.eyes and level == "basic":
            print("checking the eyes", flush=True)
            try:
                report["problems"] += check_eyes(builtin_ai, level, report)
            except Exception as exc:  # noqa: BLE001
                report["problems"].append(f"eyes: {type(exc).__name__}: {exc}")
        shutil.rmtree(builtin_ai.level_dir(level), ignore_errors=True)  # runners have little disk
    if args.meaning:
        print("checking the meaning model", flush=True)
        try:
            report["problems"] += check_meaning(report)
        except Exception as exc:  # noqa: BLE001
            report["problems"].append(f"meaning: {type(exc).__name__}: {exc}")
    if args.sound:
        print("checking the sound cleanup", flush=True)
        try:
            report["problems"] += check_sound(report)
        except Exception as exc:  # noqa: BLE001
            report["problems"].append(f"sound: {type(exc).__name__}: {exc}")
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    text = summary_table(report)
    print(text, flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text)
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
