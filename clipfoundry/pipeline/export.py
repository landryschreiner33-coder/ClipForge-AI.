"""Batch export: ZIP with MP4s, SRT captions and metadata (JSON + CSV)."""
from __future__ import annotations

import csv
import io
import json
import re
import time
import zipfile
from pathlib import Path

from .common import fmt_ts


def safe_name(text: str, fallback: str = "clip") -> str:
    name = re.sub(r"[^\w\s-]", "", text or "").strip()
    name = re.sub(r"\s+", " ", name)[:60].strip()
    return name or fallback


def clip_metadata(project: dict, clip: dict, filename: str) -> dict:
    edit = clip.get("edit") or {}
    rendered = clip.get("render_info") or {}
    start = float(edit.get("start", rendered.get("start", clip["start"])))
    end = float(edit.get("end", rendered.get("end", clip["end"])))
    return {
        "file": filename,
        "title": clip.get("title", ""),
        "hook": edit.get("hook") or clip.get("hook", ""),
        "alternative_hooks": clip.get("hooks_alt") or [],
        "caption_text": clip.get("caption_text", ""),
        "hashtags": clip.get("hashtags") or [],
        "category": clip.get("category", ""),
        "ai_estimate_score": clip.get("score", 0),
        "score_note": "AI estimate of short-form potential, not a guarantee of views",
        "score_breakdown": clip.get("scores") or {},
        "scored_by": clip.get("score_source", ""),
        "source_video": project.get("source_filename") or project.get("name"),
        "source_start": round(start, 2),
        "source_end": round(end, 2),
        "source_timestamp": f"{fmt_ts(start)} - {fmt_ts(end)}",
        "duration_seconds": clip.get("duration", 0),
    }


def build_zip(project: dict, clips: list[dict], dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    zpath = dest_dir / f"{safe_name(project['name'], 'clips')} - {stamp}.zip"
    rows = []
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i, clip in enumerate(clips, 1):
            out = Path(clip.get("output_path") or "")
            if not out.exists():
                continue
            base = f"{i:02d} - {safe_name(clip.get('title', ''), clip['id'])}"
            zf.write(out, f"{base}.mp4", compress_type=zipfile.ZIP_STORED)
            srt = out.parent / "captions.srt"
            if srt.exists():
                zf.write(srt, f"{base}.srt")
            meta = clip_metadata(project, clip, f"{base}.mp4")
            zf.writestr(f"{base}.txt", _post_text(meta))
            rows.append(meta)
        zf.writestr("metadata.json", json.dumps({"project": project["name"], "clips": rows}, indent=2,
                                                ensure_ascii=False))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["file", "title", "hook", "alternative_hooks", "hashtags", "category", "ai_estimate_score",
                    "source_timestamp", "duration_seconds", "caption_text"])
        for m in rows:
            w.writerow([m["file"], m["title"], m["hook"], " | ".join(m["alternative_hooks"]), " ".join(m["hashtags"]),
                        m["category"], m["ai_estimate_score"], m["source_timestamp"], m["duration_seconds"],
                        m["caption_text"]])
        zf.writestr("metadata.csv", "﻿" + buf.getvalue())
    return zpath


def _post_text(meta: dict) -> str:
    alts = "\n".join(f"  - {h}" for h in meta["alternative_hooks"])
    return (f"Title: {meta['title']}\nHook: {meta['hook']}\nAlternative hooks:\n{alts}\n"
            f"Hashtags: {' '.join(meta['hashtags'])}\nCategory: {meta['category']}\n"
            f"AI estimate: {meta['ai_estimate_score']}/100 (estimate, not a guarantee)\n"
            f"Source: {meta['source_video']} @ {meta['source_timestamp']}\n\nCaption:\n{meta['caption_text']}\n")
