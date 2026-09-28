"""Project pipeline: VIDEO -> TRANSCRIPT -> BEST MOMENTS -> CLIPS -> 9:16 -> CAPTIONS -> HOOKS -> EXPORT."""
from __future__ import annotations

import time
from pathlib import Path

from .. import db
from . import candidates as cand_mod
from . import postpack, render, scoring, transcribe, virality
from .audio import Loudness, loudness_envelope
from .common import Cancelled, JobContext, log, read_json, write_json
from .ffmpeg_utils import extract_audio, make_silent_wav, probe, thumbnail
from .text_utils import build_sentences

# Overall progress budget per stage
P_PROBE, P_AUDIO, P_TRANSCRIBE, P_ANALYZE, P_SCORE, P_RENDER = 0.02, 0.07, 0.45, 0.50, 0.58, 1.0


def project_dir(project: dict) -> Path:
    return Path(project["source_path"]).parent


def load_words(project: dict) -> list[dict]:
    data = read_json(project_dir(project) / "transcript.json", {})
    return transcribe.flatten_words(data) if data else []


def _options(project: dict, settings: dict) -> dict:
    opts = dict(settings)
    opts.update({k: v for k, v in (project.get("options") or {}).items() if v is not None})
    opts["min_duration"] = float(opts.get("min_duration", 20))
    opts["max_duration"] = max(opts["min_duration"] + 5, float(opts.get("max_duration", 60)))
    opts["target_duration"] = min(opts["max_duration"], max(opts["min_duration"], float(opts.get("target_duration", 35))))
    opts["clip_count"] = int(opts.get("clip_count", 5))
    return opts


def run_project(project_id: str, ctx: JobContext) -> None:
    project = db.get_project(project_id)
    if not project:
        return
    settings = db.get_settings()
    opts = _options(project, settings)
    pdir = project_dir(project)
    src = Path(project["source_path"])
    t_start = time.time()

    def stage(name: str, frac: float, msg: str) -> None:
        db.update_project(project_id, stage=name, progress=round(frac, 4), message=msg)

    ctx_report = ctx._report  # noqa: SLF001

    # ---- 1. probe
    stage("probe", 0.0, "Reading video")
    meta = probe(src)
    info = {**(project.get("info") or {}), **meta}
    db.update_project(project_id, duration=meta["duration"], width=meta["width"], height=meta["height"],
                      fps=meta["fps"], info=info)
    thumb = pdir / "thumb.jpg"
    if not thumb.exists():
        try:
            thumbnail(src, min(meta["duration"] * 0.1, 10.0), thumb, 480)
        except Exception as exc:  # noqa: BLE001
            log.warning("project thumbnail failed: %s", exc)
    ctx.check()

    # ---- 2. audio
    wav = pdir / "audio.wav"
    if not wav.exists():
        stage("audio", P_PROBE, "Extracting audio")
        if meta["has_audio"]:
            extract_audio(src, wav, meta["duration"],
                          progress=lambda f: ctx_report(P_PROBE + (P_AUDIO - P_PROBE) * f, "Extracting audio"),
                          cancel=ctx.cancelled)
        else:
            make_silent_wav(wav, meta["duration"])
    ctx.check()

    # ---- 3. transcript
    tpath = pdir / "transcript.json"
    transcript = read_json(tpath, None)
    if not transcript:
        imported = project.get("options", {}).get("transcript_file")
        if imported and Path(imported).exists():
            stage("transcribe", P_AUDIO, "Importing transcript")
            transcript = transcribe.import_transcript(Path(imported), meta["duration"])
        elif not meta["has_audio"]:
            transcript = {"language": "", "duration": meta["duration"], "source": "none", "segments": []}
        else:
            stage("transcribe", P_AUDIO, "Transcribing")
            transcript = transcribe.transcribe(wav, meta["duration"], settings, ctx, P_AUDIO, P_TRANSCRIBE)
        write_json(tpath, transcript)
    words = transcribe.flatten_words(transcript)
    info["transcript_source"] = transcript.get("source", "")
    if transcript.get("runtime"):
        info["transcription"] = {k: v for k, v in transcript["runtime"].items() if k not in ("started", "ended")}
    info["language"] = transcript.get("language", "")
    info["word_count"] = len(words)
    ctx.check()

    # ---- 4. stage 1 candidates
    stage("candidates", P_TRANSCRIBE, "Finding the best moments")
    env_path = pdir / "loudness.json"
    env = read_json(env_path, None)
    if not env:
        env = loudness_envelope(wav)
        write_json(env_path, env)
    loud = Loudness(env)
    sentences = build_sentences(words)
    pool = min(24, max(opts["clip_count"] * 2 + 2, 8))
    if sentences:
        cands = cand_mod.find_candidates(words, sentences, loud, opts, pool_size=pool)
    else:
        cands = cand_mod.fallback_windows(loud, meta["duration"], opts, pool)
    write_json(pdir / "candidates.json", [{k: v for k, v in c.items() if k != "tf"} for c in cands])
    ctx.check()

    # ---- 5. stage 2 evaluation
    stage("scoring", P_ANALYZE, "Scoring candidates")
    results, notes = scoring.evaluate(cands, sentences, opts, ctx, project["name"], P_ANALYZE, P_SCORE,
                                      words=words, loud=loud)
    min_score = float(opts.get("min_score", 50))
    chosen = scoring.select(results, opts["clip_count"], min_score)
    info["stage2"] = notes
    info["candidates_found"] = len(cands)
    info["quality"] = scoring.quality_report(results, chosen, opts["clip_count"], min_score)
    db.update_project(project_id, info=info)

    # ---- 6. create clips, each with its post package (titles, captions, hashtags... from its own words)
    db.delete_clips(project_id)
    clip_rows = []
    df = scoring.document_frequencies(sentences)
    for rank, r in enumerate(chosen):
        ctx.check()
        if r["s0"] >= 0:
            start, end = cand_mod.refine_bounds(r, sentences, meta["duration"])
        else:
            start, end = r["start"], r["end"]
        ctx.progress(P_SCORE, f"Writing post package {rank + 1} of {len(chosen)}")
        sents = [sentences[k]["text"] for k in range(r["s0"], r["s1"] + 1)] if r["s0"] >= 0 else []
        post = postpack.generate(sents, r["hook"], r["hooks_alt"], r["category"], opts, df, max(1, len(sentences)))
        clip_rows.append(db.create_clip(
            project_id, rank=rank, start=start, end=end, title=post["title"] or r["title"], hook=r["hook"],
            hooks_alt=r["hooks_alt"], caption_text=r["caption_text"], hashtags=post["hashtags"] or r["hashtags"],
            category=r["category"], score=r["score"], scores=r["scores"], score_source=r["score_source"],
            reason=r["reason"], analysis=virality.summary(r["analysis"]), post=post, edit={}, status="queued",
            duration=round(end - start, 2),
        ))

    # ---- 7. render
    project = db.get_project(project_id) or project
    project["dir"] = str(pdir)
    n = max(1, len(clip_rows))
    for i, clip in enumerate(clip_rows):
        ctx.check()
        lo = P_SCORE + (P_RENDER - P_SCORE) * i / n
        hi = P_SCORE + (P_RENDER - P_SCORE) * (i + 1) / n
        msg = f"Rendering clip {i + 1} of {len(clip_rows)}"
        stage("render", lo, msg)
        db.update_clip(clip["id"], status="rendering", progress=0)
        sub = JobContext(lambda f, m, lo=lo, hi=hi, cid=clip["id"], msg=msg: (
            ctx_report(lo + (hi - lo) * f, msg), db.update_clip(cid, progress=round(f, 3))),
            ctx.cancelled)
        try:
            out = render.render_clip(project, clip, words, settings, sub)
            db.update_clip(clip["id"], status="ready", progress=1.0, error="", **out)
        except Cancelled:
            db.update_clip(clip["id"], status="error", error="Cancelled")
            raise
        except Exception as exc:  # keep going with the other clips
            log.exception("render failed")
            db.update_clip(clip["id"], status="error", error=str(exc)[:500])
    info["processing_seconds"] = round(time.time() - t_start, 1)
    db.update_project(project_id, info=info)


def render_single(clip_id: str, ctx: JobContext) -> None:
    clip = db.get_clip(clip_id)
    if not clip:
        return
    project = db.get_project(clip["project_id"])
    if not project:
        return
    project["dir"] = str(project_dir(project))
    settings = db.get_settings()
    db.update_clip(clip_id, status="rendering", progress=0, error="")
    sub = JobContext(lambda f, m: db.update_clip(clip_id, progress=round(f, 3)), ctx.cancelled)
    try:
        out = render.render_clip(project, clip, load_words(project), settings, sub)
        db.update_clip(clip_id, status="ready", progress=1.0, error="", **out)
    except Cancelled:
        db.update_clip(clip_id, status="error", error="Cancelled")
        raise
    except Exception as exc:
        log.exception("render failed")
        db.update_clip(clip_id, status="error", error=str(exc)[:500])


def version_dir(project: dict, version: dict) -> Path:
    return project_dir(project) / "clips" / version["clip_id"] / "versions" / version["id"]


def render_version(version_id: str, ctx: JobContext) -> None:
    """Render one alternative version: the clip's current edit plus the version's overrides."""
    version = db.get_version(version_id)
    clip = db.get_clip(version["clip_id"]) if version else None
    project = db.get_project(clip["project_id"]) if clip else None
    if not version or not clip or not project:
        return
    project["dir"] = str(project_dir(project))
    merged = {**clip, "edit": {**(clip.get("edit") or {}), **(version.get("edit") or {})}}
    db.update_version(version_id, status="rendering", progress=0, error="")
    sub = JobContext(lambda f, m: db.update_version(version_id, progress=round(f, 3)), ctx.cancelled)
    try:
        out = render.render_clip(project, merged, load_words(project), db.get_settings(), sub,
                                 out_dir=version_dir(project, version))
        db.update_version(version_id, status="ready", progress=1.0, error="", **out)
    except Cancelled:
        db.update_version(version_id, status="error", error="Cancelled")
        raise
    except Exception as exc:
        log.exception("version render failed")
        db.update_version(version_id, status="error", error=str(exc)[:500])
