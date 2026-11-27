"""Clip quality benchmark: the same footage through two versions of ClipForge's clip finder, side by side.

    # 1. make the representative footage (spoken with espeak-ng; nothing is downloaded)
    python scripts/clip_quality_benchmark.py make --out /tmp/bench/footage
    # 2. run each version's real pipeline on it, in an empty data folder each time
    CLIPFOUNDRY_DATA=/tmp/bench/new python scripts/clip_quality_benchmark.py run /tmp/bench/footage --out new.json
    CLIPFOUNDRY_DATA=/tmp/bench/old python scripts/clip_quality_benchmark.py run /tmp/bench/footage \
        --code /path/to/older/checkout --out old.json
    # (add --explain old.json to the second run to score the older version's clips with the newer rules too)
    # 3. write the report
    python scripts/clip_quality_benchmark.py compare old.json new.json --out report.md

`run` also takes a folder of your own footage: one sub-folder per video with audio.wav (16 kHz mono) and
transcript.json (the app's transcript format, as written next to every project).

What `run` measures, with the app's default settings (Highlights, deep analysis on, Remove pauses "light"):
which moments are promoted to clips, which are rejected and why (scoring.quality_report), the Viral Potential
estimate and its flags, and for each promoted clip what "Remove pauses" takes out and which pauses it keeps, plus the
suggested tighter start and end and the plain reasons (only in versions that have pipeline/trims.py and
virality.reasons). Nothing is uploaded and no clip is rendered.

The built-in footage is synthetic: a computer voice reads three scripts written to look like a podcast, a game
stream and a tutorial, with the traps real footage has (warm-up words, a sponsor read, an outro, a part that leans
on earlier parts, repeated lines, dead air, a pause after a question, a shout without words). Word times come from
each sentence's spoken length, not from a transcriber, and every word gets the same confidence. It shows what the
code does with those patterns; it is not a measure of how real viewers react.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE / "clip_benchmark"
RATE = 16000
GAP = 0.32          # silence between sentences
PARA = 0.7          # silence between paragraphs


# ------------------------------------------------------------------ 1. footage
def _say(text: str, path: Path, speed: int, voice: str) -> list[float]:
    subprocess.run(["espeak-ng", "-v", voice, "-s", str(speed), "-w", str(path), text], check=True,
                   capture_output=True)
    with wave.open(str(path), "rb") as w:
        rate, n = w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    import numpy as np

    pcm = np.frombuffer(raw, np.int16).astype(np.float32)
    if rate != RATE:  # espeak-ng speaks at 22.05 kHz: resample to the app's 16 kHz
        idx = np.arange(0, len(pcm), rate / RATE)
        pcm = np.interp(idx, np.arange(len(pcm)), pcm)
    voiced = np.nonzero(np.abs(pcm) > 300)[0]
    if len(voiced):
        pcm = pcm[max(0, voiced[0] - 160):voiced[-1] + 160]
    return pcm.tolist()


def _words(sentence: str, start: float, length: float) -> list[dict]:
    """Word times spread over the sentence by letters (plus one for the gap after each word)."""
    parts = sentence.split()
    weights = [len(re.sub(r"[^\w]", "", p)) + 1.5 for p in parts]
    total = sum(weights) or 1.0
    out, t = [], start
    for p, wgt in zip(parts, weights):
        d = length * wgt / total
        out.append({"w": p, "start": round(t, 3), "end": round(t + d * 0.85, 3), "p": 0.9})
        t += d
    return out


def _cheer(seconds: float, seed: int) -> list[float]:
    """A loud stretch without words standing in for a shout, laughter or a crowd: noise louder than the voice, faded
    in and out. Nothing in the transcript marks it; only the loudness shows it."""
    import numpy as np

    n = int(seconds * RATE)
    noise = np.random.default_rng(seed).normal(0.0, 7000.0, n)
    fade = np.minimum(1.0, np.minimum(np.arange(n), np.arange(n)[::-1]) / (0.08 * RATE))
    return (noise * fade).tolist()


def make(out: Path, speed: int = 160, voice: str = "en-us") -> None:
    import numpy as np

    out.mkdir(parents=True, exist_ok=True)
    for script in sorted(SCRIPTS.glob("*.txt")):
        audio: list[float] = []
        segments = []
        with tempfile.TemporaryDirectory() as tmp:
            for para in script.read_text().split("\n\n"):
                lines = [ln for ln in para.splitlines() if ln and not ln.startswith("#")]
                text = " ".join(lines)
                for piece in re.split(r"(\[(?:pause|dead|cheer) [\d.]+\])", text):
                    piece = piece.strip()
                    mark = re.fullmatch(r"\[(pause|dead|cheer) ([\d.]+)\]", piece)
                    if mark and mark.group(1) == "cheer":
                        audio += _cheer(float(mark.group(2)), len(segments))
                        continue
                    if mark:
                        audio += [0.0] * int(float(mark.group(2)) * RATE)
                        continue
                    for sent in re.findall(r"[^.!?]+[.!?]+", piece):
                        sent = sent.strip()
                        pcm = _say(sent, Path(tmp) / "s.wav", speed, voice)
                        start = len(audio) / RATE
                        audio += pcm
                        segments.append({"start": round(start, 3), "end": round(len(audio) / RATE, 3),
                                         "text": sent, "words": _words(sent, start, len(pcm) / RATE)})
                        audio += [0.0] * int(GAP * RATE)
                audio += [0.0] * int(PARA * RATE)
        folder = out / script.stem
        folder.mkdir(exist_ok=True)
        pcm = np.clip(np.asarray(audio), -32768, 32767).astype(np.int16)
        with wave.open(str(folder / "audio.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm.tobytes())
        duration = len(pcm) / RATE
        (folder / "transcript.json").write_text(json.dumps(
            {"language": "en", "duration": duration, "source": "benchmark (espeak-ng; estimated word times)",
             "segments": segments}))
        (folder / "about.txt").write_text(script.read_text().splitlines()[0].lstrip("# ") + "\n")
        print(f"{script.stem}: {duration:.0f} s, {sum(len(s['words']) for s in segments)} words")


# ------------------------------------------------------------------ 2. run
def _git(code: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(code), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001 - a copy without git history
        return "unknown"


def run(footage: Path, code: Path, out: Path, explain: Path | None = None) -> None:
    if not os.environ.get("CLIPFOUNDRY_DATA"):
        sys.exit("Set CLIPFOUNDRY_DATA to an empty benchmark folder (never your real data).")
    os.environ.setdefault("CLIPFOUNDRY_WORKERS", "off")
    sys.path.insert(0, str(code))
    from clipfoundry import config, db
    from clipfoundry.pipeline import candidates as cand_mod
    from clipfoundry.pipeline import postpack, process, render, scoring, virality
    from clipfoundry.pipeline.audio import loudness_envelope
    from clipfoundry.pipeline.common import JobContext, write_json

    try:
        from clipfoundry.pipeline import trims
    except ImportError:
        trims = None
    db.init()
    db.save_settings({"onboarding_done": True})
    settings = {**config.DEFAULT_SETTINGS, **db.get_settings()}
    report = {"code": _git(code), "has_trims": trims is not None, "has_reasons": hasattr(virality, "reasons"),
              "settings": {k: settings.get(k) for k in ("clip_count", "min_duration", "target_duration",
                                                        "max_duration", "min_score", "deep_analysis", "silence")},
              "videos": []}
    for folder in sorted(p for p in footage.iterdir() if (p / "transcript.json").exists()):
        work = Path(os.environ["CLIPFOUNDRY_DATA"]) / "footage" / folder.name
        work.mkdir(parents=True, exist_ok=True)
        for name in ("audio.wav", "transcript.json"):
            (work / name).write_bytes((folder / name).read_bytes())
        write_json(work / "loudness.json", loudness_envelope(work / "audio.wav"))
        tr = json.loads((work / "transcript.json").read_text())
        p = db.create_project(folder.name, source_path=str(work / "audio.wav"), status="ready",
                              duration=tr["duration"], width=1920, height=1080, fps=30.0,
                              info={"duration": tr["duration"], "has_audio": True, "has_video": False})
        t0 = time.time()
        prep = process.load_prepared(p["id"])
        ctx = JobContext()
        cands = process.candidate_pool(prep, ctx)
        chosen = process.evaluate_select(prep, cands, ctx)
        q = prep.info.get("quality") or {}
        words = prep.words
        clips = []
        df = scoring.document_frequencies(prep.sentences)
        new_cuts = hasattr(render, "heard")
        for r in chosen:
            # the clip's real start and end, exactly as create_clips sets them
            if r.get("bounds"):
                start, end = r["bounds"]["start"], r["bounds"]["end"]
            elif r["s0"] >= 0:
                start, end = cand_mod.refine_bounds(r, prep.sentences, prep.meta["duration"],
                                                    *([prep.loud] if new_cuts else []))
            else:
                start, end = r["start"], r["end"]
            a = r["analysis"]
            # versions with render.heard keep reactions without words when Remove pauses cuts the dead air
            loud = virality.wordless_loud(words, prep.loud, start, end) if new_cuts else None
            keep = render.keep_segments(words, start, end, "light", 30.0, **({"loud": loud} if new_cuts else {}))
            sents = [prep.sentences[k]["text"] for k in range(r["s0"], r["s1"] + 1)] if r["s0"] >= 0 else []
            post = postpack.generate(sents, r["hook"], r["hooks_alt"], r["category"], prep.opts, df,
                                     max(1, len(prep.sentences)), use_ai=False)
            item = {"start": round(start, 2), "end": round(end, 2), "length": round(end - start, 1),
                    "after_pauses": round(sum(b - a_ for a_, b in keep), 1), "score": r.get("score"),
                    "viral_potential": a.get("viral_potential"),
                    "structure": (a.get("structure") or {}).get("label", ""),
                    "flags": [f"{f['label']} ({f['severity']}): {f.get('detail', '')}" for f in a.get("flags", [])],
                    "text": r.get("caption_text") or " ".join(w["w"] for w in words if start <= w["start"] < end),
                    "title": post.get("title"), "hashtags": post.get("hashtags")}
            guide = post.get("guide")
            if guide:
                item["titles"] = [{"kind": o["label"], "text": o["text"]} for o in guide["options"]]
                item["title_picks"] = {k: guide[k] for k in ("youtube", "tiktok") if guide.get(k)}
            if trims is not None:
                t = trims.suggest(words, start, end, silence="light", all_words=words,
                                  **({"loud": loud} if new_cuts else {}))
                item["trims"] = [{"label": s_["label"], "seconds": s_["seconds"], "why": s_["why"]}
                                 for s_ in t["suggestions"]]
                item["kept_pauses"] = t["kept_pauses"]
            if hasattr(virality, "reasons"):
                item["reasons"] = virality.reasons(virality.summary(a))
            clips.append(item)
        # the other version's clips, scored by this version: why a clip it promoted is now changed or left out
        explained = []
        other = next((v for v in json.loads(explain.read_text())["videos"] if v["name"] == folder.name), None) \
            if explain else None
        if other:
            feats = cand_mod.sentence_features(prep.sentences, words)
            for c in other["promoted"]:
                inside = [k for k, s_ in enumerate(prep.sentences)
                          if s_["start"] >= c["start"] - 0.6 and s_["end"] <= c["end"] + 0.6]
                if not inside:
                    continue
                r = virality.finalize(virality.analyze(inside[0], inside[-1], prep.sentences, feats, words,
                                                       prep.loud, prep.opts))
                fl = [f"{f['label']}: {f.get('detail', '')}" for f in r["flags"]]
                nxt = next((s_["start"] for s_ in prep.sentences if s_["start"] >= c["end"]), c["end"] + 3.0)
                cut_off = [x for x in getattr(virality, "wordless_loud", lambda *a: [])(
                    words, prep.loud, c["end"], min(nxt, c["end"] + 3.0)) if x[0] > c["end"] + 0.05]
                if cut_off:
                    fl.append(f"Cuts off the reaction: stops {cut_off[0][0] - c['end']:.1f} s before a loud moment "
                              "without words")
                explained.append({"start": c["start"], "end": c["end"], "viral_potential": r["viral_potential"],
                                  "blocked": r["blocked"], "flags": fl})
        about = (folder / "about.txt").read_text().strip() if (folder / "about.txt").exists() else ""
        report["videos"].append({"name": folder.name, "explained": explained, "about": about,
                                 "duration": round(tr["duration"], 1), "seconds": round(time.time() - t0, 1),
                                 "evaluated": q.get("evaluated"), "passed": q.get("passed"),
                                 "reject_counts": q.get("reject_counts"), "rejected": q.get("rejected", []),
                                 "promoted": clips})
        print(f"{folder.name}: {len(clips)} promoted, {len(q.get('rejected', []))} rejected listed")
    out.write_text(json.dumps(report, indent=1))


# ------------------------------------------------------------------ 3. compare
def _span(c: dict) -> str:
    def mmss(s: float) -> str:
        return f"{int(s // 60)}:{s % 60:04.1f}"
    return f"{mmss(c['start'])}–{mmss(c['end'])}"


def _quote(text: str, n: int = 150) -> str:
    text = " ".join(str(text).split())
    return "“" + (text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " …") + "”"


def _overlap(a: dict, b: dict) -> float:
    inter = max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    return inter / max(1e-6, min(a["end"] - a["start"], b["end"] - b["start"]))


def compare(old_path: Path, new_path: Path, out: Path) -> None:
    old, new = json.loads(old_path.read_text()), json.loads(new_path.read_text())
    st = new["settings"]
    lines = [f"# Clip quality benchmark: before ({old['code']}) and after ({new['code']})", "",
             f"The same footage through both versions with the app's default settings: {st['clip_count']} clips "
             f"wanted, {st['min_duration']:.0f} to {st['max_duration']:.0f} s (ideal {st['target_duration']:.0f} s), "
             f"Viral Potential at least {st['min_score']:.0f}, deep analysis "
             f"{'on' if st['deep_analysis'] else 'off'}, Remove pauses “{st['silence']}”.", "",
             "The footage is synthetic: a computer voice (espeak-ng) reads three scripts written like real videos, "
             "with the traps real footage has. Word times are estimated, not transcribed. This shows what each "
             "version does with those patterns; it is not a measure of how viewers react.", ""]
    totals = {"before": 0, "after": 0}
    for nv in new["videos"]:
        ov = next((v for v in old["videos"] if v["name"] == nv["name"]), {"promoted": []})
        totals["before"] += len(ov["promoted"])
        totals["after"] += len(nv["promoted"])
        lines += [f"## {nv['name'].replace('_', ' ').capitalize()}", "", nv.get("about", ""), "",
                  f"{nv['duration']:.0f} s of footage. Before: {len(ov['promoted'])} clips. After: "
                  f"{len(nv['promoted'])} clips.", ""]
        why_now = {(e["start"], e["end"]): e for e in nv.get("explained", [])}
        for oc in ov["promoted"]:
            match = max(nv["promoted"], key=lambda c: _overlap(oc, c), default=None)
            e = why_now.get((oc["start"], oc["end"]))
            reasons = "; ".join(e["flags"]) if e and e["flags"] else ""
            if match is None or _overlap(oc, match) < 0.5:
                lines.append(f"- **Rejected now** (was promoted, {_span(oc)}, {oc['length']:.0f} s) "
                             f"{_quote(oc['text'], 110)}" + (f" Why: {reasons}." if reasons else ""))
            elif (round(match["start"], 1), round(match["end"], 1)) != (round(oc["start"], 1), round(oc["end"], 1)):
                lines.append(f"- **Trimmed or moved** {_span(oc)} → {_span(match)} ({oc['length']:.0f} s → "
                             f"{match['length']:.0f} s) {_quote(match['text'], 90)}"
                             + (f" The old cut, scored now: {reasons}." if reasons else ""))
            else:
                lines.append(f"- **Kept** {_span(match)} ({match['length']:.0f} s) {_quote(match['text'], 90)}")
        for c in nv["promoted"]:
            if all(_overlap(c, oc) < 0.5 for oc in ov["promoted"]):
                lines.append(f"- **Promoted now** (was not a clip) {_span(c)} ({c['length']:.0f} s, Viral Potential "
                             f"{c['viral_potential']}) {_quote(c['text'], 110)}")
        lines += ["", "### The clips after, with their reasons", ""]
        for c in nv["promoted"]:
            oc = next((x for x in ov["promoted"] if _overlap(x, c) >= 0.5), None)
            lines += [f"**{_span(c)}** ({c['length']:.0f} s, Viral Potential {c['viral_potential']}, "
                      f"{c['structure']}) {_quote(c['text'])}", ""]
            for r in c.get("reasons", []):
                lines.append(f"- {r['area']} {'✓' if r['good'] else '✗' if r['good'] is False else '·'} {r['text']}")
            for f in c["flags"]:
                lines.append(f"- Flag: {f}")
            for t in c.get("titles", []):
                lines.append(f"- Title ({t['kind']}): {t['text']}")
            picks = c.get("title_picks") or {}
            for where, pick in picks.items():
                titles = c.get("titles") or []
                if titles and isinstance(pick.get("recommended"), int) and pick["recommended"] < len(titles):
                    lines.append(f"- Recommended for {'YouTube' if where == 'youtube' else 'TikTok'}: "
                                 f"“{titles[pick['recommended']]['text']}”. {pick.get('why', '')}")
            for t in c.get("trims", []):
                lines.append(f"- Suggested trim, {t['label'].lower()} ({t['seconds']:+.1f} s): {t['why']}")
            for k in c.get("kept_pauses", []):
                lines.append(f"- Remove pauses keeps the pause at {k['at']:.1f} s ({k['why'].lower()}).")
            after = f"{c['length']:.1f} s → {c['after_pauses']:.1f} s"
            lines.append(f"- Remove pauses: {after}" + (f" (the old version cut this clip to {oc['after_pauses']:.1f} "
                                                        f"s)." if oc and oc["start"] == c["start"]
                                                        and oc["end"] == c["end"] else "."))
            lines.append("")
        if nv["rejected"]:
            lines += ["### Rejected after", ""]
            for r in nv["rejected"][:6]:
                lines.append(f"- {_span(r)} (score {r['score']}) {_quote(r['text'], 100)}: {'; '.join(r['reasons'])}")
            lines.append("")
    lines += [f"In all: {totals['before']} clips before, {totals['after']} after."]
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--out", required=True)
    m.add_argument("--speed", type=int, default=160)
    r = sub.add_parser("run")
    r.add_argument("footage")
    r.add_argument("--code", default=str(HERE.parent), help="the ClipForge checkout to run")
    r.add_argument("--out", required=True)
    r.add_argument("--explain", help="another version's run JSON: score its clips with this version too")
    c = sub.add_parser("compare")
    c.add_argument("old")
    c.add_argument("new")
    c.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "make":
        make(Path(a.out), a.speed)
    elif a.cmd == "run":
        run(Path(a.footage), Path(a.code).resolve(), Path(a.out), Path(a.explain) if a.explain else None)
    else:
        compare(Path(a.old), Path(a.new), Path(a.out))


if __name__ == "__main__":
    main()
