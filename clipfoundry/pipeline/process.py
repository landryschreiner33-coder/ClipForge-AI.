"""Project pipeline: VIDEO -> TRANSCRIPT -> BEST MOMENTS -> CLIPS -> 9:16 -> CAPTIONS -> HOOKS -> EXPORT."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import db, gpu
from . import candidates as cand_mod
from . import blueprint, postpack, render, scoring, transcribe, virality
from .audio import Loudness, loudness_envelope
from .common import Cancelled, JobContext, log, read_json, write_json
from .ffmpeg_utils import extract_audio, make_silent_wav, probe, thumbnail
from .text_utils import build_sentences

# Overall progress budget per stage
P_PROBE, P_AUDIO, P_TRANSCRIBE, P_ANALYZE, P_SCORE, P_RENDER = 0.02, 0.07, 0.45, 0.50, 0.58, 1.0


def _duration(project: dict) -> float | None:
    return float(project.get("duration") or 0) or None


def project_dir(project: dict) -> Path:
    return Path(project["source_path"]).parent


def load_words(project: dict) -> list[dict]:
    data = read_json(project_dir(project) / "transcript.json", {})
    return transcribe.flatten_words(data) if data else []


def _options(project: dict, settings: dict) -> dict:
    opts = dict(settings)
    opts.update({k: v for k, v in (project.get("options") or {}).items() if v is not None})
    opts["origin"] = project.get("origin") or "manual"  # Autopilot work is unattended (pipeline/nvidia.py)
    opts["min_duration"] = float(opts.get("min_duration", 20))
    opts["max_duration"] = max(opts["min_duration"] + 5, float(opts.get("max_duration", 60)))
    opts["target_duration"] = min(opts["max_duration"], max(opts["min_duration"], float(opts.get("target_duration", 35))))
    opts["clip_count"] = int(opts.get("clip_count", 5))
    return opts


@dataclass
class Prepared:
    """Everything the later stages need once a project's video has been read and transcribed."""
    project: dict
    settings: dict
    opts: dict
    pdir: Path
    meta: dict
    info: dict
    words: list[dict]
    sentences: list[dict]
    loud: Loudness
    t_start: float = field(default_factory=time.time)

    @property
    def id(self) -> str:
        return self.project["id"]

    def stage(self, name: str, frac: float, msg: str) -> None:
        db.update_project(self.id, stage=name, progress=round(frac, 4), message=msg)

    def save_info(self) -> None:
        db.update_project(self.id, info=self.info)


def prepare(project_id: str, ctx: JobContext, gpu_policy: dict | None = None) -> Prepared | None:
    """Stages 1-3: read the video, extract the audio, transcribe (or import) the speech, measure loudness.

    `gpu_policy` (autopilot) can make transcription wait for free GPU memory and forbid a CPU fallback:
    {"need_free_mb": int, "max_wait_s": float, "job_id": str, "allow_cpu_fallback": bool}."""
    project = db.get_project(project_id)
    if not project:
        return None
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
            policy = gpu_policy or {}
            # one heavy GPU job at a time (app + autopilot worker); the transcription itself is unchanged
            with gpu.manager.heavy("transcription", project["name"], policy.get("job_id", ""), ctx.cancelled,
                                   need_free_mb=int(policy.get("need_free_mb") or 0),
                                   max_wait_s=policy.get("max_wait_s"),
                                   on_wait=lambda m: stage("transcribe", P_AUDIO, m)):
                stage("transcribe", P_AUDIO, "Transcribing")
                transcript = transcribe.transcribe(wav, meta["duration"], settings, ctx, P_AUDIO, P_TRANSCRIBE,
                                                   allow_cpu_fallback=policy.get("allow_cpu_fallback", True))
            gpu.manager.record_transcription(transcript.get("runtime") or {}, project["name"])
        write_json(tpath, transcript)
    words = transcribe.flatten_words(transcript)
    info["transcript_source"] = transcript.get("source", "")
    if transcript.get("runtime"):
        info["transcription"] = {k: v for k, v in transcript["runtime"].items() if k not in ("started", "ended")}
    info["language"] = transcript.get("language", "")
    info["word_count"] = len(words)
    ctx.check()
    env_path = pdir / "loudness.json"
    env = read_json(env_path, None)
    if not env:
        env = loudness_envelope(wav)
        write_json(env_path, env)
    return Prepared(project, settings, opts, pdir, meta, info, words, build_sentences(words), Loudness(env), t_start)


def load_prepared(project_id: str) -> Prepared | None:
    """The result of `prepare` rebuilt from the files it wrote (no decoding, no transcription)."""
    project = db.get_project(project_id)
    if not project:
        return None
    pdir = project_dir(project)
    transcript = read_json(pdir / "transcript.json", None)
    env = read_json(pdir / "loudness.json", None)
    if transcript is None or env is None:
        return None
    settings = db.get_settings()
    words = transcribe.flatten_words(transcript)
    info = project.get("info") or {}
    meta = {k: info.get(k, project.get(k)) for k in ("duration", "width", "height", "fps", "has_audio", "has_video")}
    return Prepared(project, settings, _options(project, settings), pdir, meta, info, words, build_sentences(words),
                    Loudness(env))


def candidate_pool(p: Prepared, ctx: JobContext) -> list[dict]:
    """Stage 4: cheap scoring of every sentence-aligned window; the best distinct ones form the pool."""
    p.stage("candidates", P_TRANSCRIBE, "Finding the best moments")
    pool = int(p.opts.get("pool_size") or 0) or min(24, max(p.opts["clip_count"] * 2 + 2, 8))
    if p.sentences:
        overlap = 0.5 if p.opts.get("deep_analysis") else 0.15  # a broad pool; overlaps are resolved later
        cands = cand_mod.find_candidates(p.words, p.sentences, p.loud, p.opts, pool_size=pool, max_overlap=overlap)
    else:
        cands = cand_mod.fallback_windows(p.loud, p.meta["duration"], p.opts, pool)
    for k, c in enumerate(cands):
        c["cid"] = k
    write_json(p.pdir / "candidates.json", [{k: v for k, v in c.items() if k != "tf"} for c in cands])
    p.info["candidates_found"] = len(cands)
    ctx.check()
    return cands


def evaluate_select(p: Prepared, cands: list[dict], ctx: JobContext, trend_keywords: list[str] | None = None,
                    prior: list[dict] | None = None) -> list[dict]:
    """Stage 5: evaluate the pool and choose the clips (quality first; never padded with weak ones)."""
    p.stage("scoring", P_ANALYZE, "Scoring candidates")
    min_score = float(p.opts.get("min_score", 50))
    if p.opts.get("deep_analysis"):
        from . import deep

        chosen, results, notes = deep.evaluate_select(
            p.sentences, p.words, p.loud, p.opts, ctx, p.project["name"], cands,
            video_path=p.project.get("source_path", ""), meta=p.meta, lo=P_ANALYZE, hi=P_SCORE,
            trend_keywords=trend_keywords, prior=prior)
        report = scoring.quality_report(results, chosen, p.opts["clip_count"], min_score)
        report["rejected"] = notes.pop("rejected", [])[:12] or report["rejected"]
        report["stages"] = notes.get("stages", {})
        p.info["candidates"] = notes.pop("candidates", [])
    else:
        results, notes = scoring.evaluate(cands, p.sentences, p.opts, ctx, p.project["name"], P_ANALYZE, P_SCORE,
                                          words=p.words, loud=p.loud)
        chosen = scoring.select(results, p.opts["clip_count"], min_score)
        report = scoring.quality_report(results, chosen, p.opts["clip_count"], min_score)
    p.info["stage2"] = notes
    p.info["quality"] = report
    p.save_info()
    return chosen


def create_clips(p: Prepared, chosen: list[dict], ctx: JobContext, replace_existing: bool = True,
                 durable: bool = False) -> list[dict]:
    """Stage 6: one clip per chosen moment, each with its post package written from its own words.
    `replace_existing=False` adds to the project's clips (post-live analysis next to the live clips)."""
    first_rank = 0
    if replace_existing and not durable:
        db.delete_clips(p.id)
    elif not durable:
        first_rank = len(db.list_clips(p.id))
    rows = []
    retained = db.list_clips(p.id) if durable and replace_existing else []
    df = scoring.document_frequencies(p.sentences)
    for rank, r in enumerate(chosen, first_rank):
        ctx.check()
        if r.get("bounds"):
            start, end = r["bounds"]["start"], r["bounds"]["end"]
        elif r["s0"] >= 0:
            start, end = cand_mod.refine_bounds(r, p.sentences, p.meta["duration"])
        else:
            start, end = r["start"], r["end"]
        stable = {}
        if durable:
            clip_id = hashlib.sha256(f"autopilot:{p.id}:{rank}:{start:.6f}:{end:.6f}".encode()).hexdigest()[:32]
            existing = db.get_clip(clip_id)
            if existing is None:
                existing = next((c for c in retained if c["rank"] == rank and
                                 abs(c["start"] - start) < 1e-6 and abs(c["end"] - end) < 1e-6), None)
            if existing is not None:
                rows.append(existing)
                continue
            stable = {"id": clip_id}
        ctx.progress(P_SCORE, f"Writing post package {rank - first_rank + 1} of {len(chosen)}")
        sents = [p.sentences[k]["text"] for k in range(r["s0"], r["s1"] + 1)] if r["s0"] >= 0 else []
        post = postpack.generate(sents, r["hook"], r["hooks_alt"], r["category"], p.opts, df,
                                 max(1, len(p.sentences)))
        rows.append(db.create_clip(
            p.id, rank=rank, start=start, end=end, title=post["title"] or r["title"], hook=r["hook"],
            hooks_alt=r["hooks_alt"], caption_text=r["caption_text"], hashtags=post["hashtags"] or r["hashtags"],
            category=r["category"], score=r["score"], scores=r["scores"], score_source=r["score_source"],
            reason=r["reason"], analysis=virality.summary(r["analysis"]), post=post, edit={}, status="queued",
            duration=round(end - start, 2), **stable,
        ))
    return rows


def render_clips(p: Prepared, clip_rows: list[dict], ctx: JobContext, lo: float = P_SCORE,
                 hi_total: float = P_RENDER) -> None:
    """Stage 7: render every clip; one failed render does not stop the others."""
    project = db.get_project(p.id) or p.project
    project["dir"] = str(p.pdir)
    ctx_report = ctx._report  # noqa: SLF001
    n = max(1, len(clip_rows))
    for i, clip in enumerate(clip_rows):
        ctx.check()
        a = lo + (hi_total - lo) * i / n
        b = lo + (hi_total - lo) * (i + 1) / n
        msg = f"Rendering clip {i + 1} of {len(clip_rows)}"
        p.stage("render", a, msg)
        db.update_clip(clip["id"], status="rendering", progress=0)
        sub = JobContext(lambda f, m, a=a, b=b, cid=clip["id"], msg=msg: (
            ctx_report(a + (b - a) * f, m), db.update_clip(cid, progress=round(f, 3))),
            ctx.cancelled)
        try:
            plan = blueprint.for_render(clip, _duration(project), p.words)  # None for manual clips
            out = render.render_clip(project, clip, p.words, p.settings, sub, blueprint=plan)
            db.update_clip(clip["id"], status="ready", progress=1.0, error="", **out)
        except Cancelled:
            db.update_clip(clip["id"], status="error", error="Cancelled")
            raise
        except Exception as exc:  # keep going with the other clips
            log.exception("render failed")
            db.update_clip(clip["id"], status="error", error=str(exc)[:500])


def run_project(project_id: str, ctx: JobContext, gpu_policy: dict | None = None) -> None:
    """The whole pipeline for one project (manual projects and the CLI)."""
    p = prepare(project_id, ctx, gpu_policy)
    if not p:
        return
    cands = candidate_pool(p, ctx)
    chosen = evaluate_select(p, cands, ctx)
    rows = create_clips(p, chosen, ctx)
    render_clips(p, rows, ctx)
    p.info["processing_seconds"] = round(time.time() - p.t_start, 1)
    p.save_info()


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
    sub = JobContext(lambda f, m: (db.update_clip(clip_id, progress=round(f, 3)), ctx.progress(f, m)), ctx.cancelled)
    try:
        words = load_words(project)
        plan = blueprint.for_render(clip, _duration(project), words)  # None for manual clips
        out = render.render_clip(project, clip, words, settings, sub, blueprint=plan)
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
        words = load_words(project)
        plan = blueprint.for_render(clip, _duration(project), words, version.get("edit") or {}, version_id)
        out = render.render_clip(project, merged, words, db.get_settings(), sub, out_dir=version_dir(project, version),
                                 blueprint=plan)
        db.update_version(version_id, status="ready", progress=1.0, error="", **out)
    except Cancelled:
        db.update_version(version_id, status="error", error="Cancelled")
        raise
    except Exception as exc:
        log.exception("version render failed")
        db.update_version(version_id, status="error", error=str(exc)[:500])
