"""Following your script: the rough cut of a project that has one.

When a project carries a script (video_flow.create's `script`, or Script → Use this script on the editor page),
the cut follows it instead of the recordings' order: studio/script.py finds every spoken line in the transcribed
words and picks its best take, and this module turns that into the plan. One clip per run of lines said one after
another in the same recording, in script order, the best take of each line; the other takes of a line follow it
switched off, so "Use this take" on the editor page swaps them (video_flow.apply_edit, `use_take`); what was said
but is not in the script waits at the end, switched off; a script heading becomes a chapter. Pictures, music and
sound effects come from smart_edit as in any smart edit. The notes say what was found, what was not, and why.

Nothing is invented: a line the footage never says gets no clip and is listed; the words are the owner's own.
"""
from __future__ import annotations

from ..pipeline.text_utils import build_sentences
from . import engine, smart_edit

LEAD_S, TAIL_S = 0.15, 0.25  # around a take's first and last word (never into the word before or after)
METHOD = "script"


def bounds(ws: list[dict], i0: int, i1: int, length_ms: int) -> tuple[int, int]:
    """The in/out times (ms) of words i0..i1 with a little room, never taking in the word before or after."""
    a, b = ws[i0]["start"] - LEAD_S, ws[i1]["end"] + TAIL_S
    if i0 > 0:
        a = max(a, ws[i0 - 1]["end"] + 0.02)
    if i1 + 1 < len(ws):
        b = min(b, ws[i1 + 1]["start"] - 0.02)
    return max(0, int(a * 1000)), max(int(a * 1000) + 250, min(length_ms, int(b * 1000)))


def quality_words(q: float | None) -> str:
    if q is None:
        return ""
    return "said cleanly" if q >= 0.85 else "said with a few slips" if q >= 0.65 else "said roughly"


def assemble(project: dict, assets: dict[str, dict], words: dict[str, list[dict]], values: dict, script: dict, *,
             ctx: dict | None = None) -> dict:
    """The plan that follows `script` (video_flow.script_payload's shape). `ctx` is what prepare_smart got ready
    (music, sound effects); ClipForge AI's advice is not used, the script decides."""
    from . import script as script_mod

    ctx = ctx or {}
    brief = project.get("brief") or {}
    opts = smart_edit.options(values, brief)
    feel = values.get("feel") if values.get("feel") in ("calm", "balanced", "energetic") else "balanced"
    t_type, t_ms = smart_edit.transition_for(values, feel)
    lines = script.get("lines") or []
    videos = [aid for aid in project["asset_ids"] if (assets.get(aid) or {}).get("kind") == "video"]
    transcripts = {aid: words[aid] for aid in videos if words.get(aid)}
    result = script_mod.match(lines, transcripts, videos)
    notes: list = script_mod.report(result, lines)
    text_of = {ln["n"]: ln["text"] for ln in lines}
    line_of = {m["n"]: m for m in result["lines"]}
    stats = {"pauses_cut": 0, "seconds_saved": 0.0, "trimmed_s": 0.0, "retakes": 0, "takes": 0, "chatter": 0,
             "stumbles": 0, "ai_left_out": 0, "fit_left_out": 0, "fillers": 0, "overlays": 0, "effects": 0,
             "music": "", "cold_open": "", "lines_found": result["stats"]["matched"] + result["stats"]["weak"],
             "lines_missing": result["stats"]["missing"], "alternatives": result["stats"]["alternatives"],
             "off_script_s": result["stats"]["off_script_s"]}
    clips: list[dict] = []
    outline: list[dict] = []
    clip_of_line: dict[int, str] = {}
    takes_of_line: dict[int, list[dict]] = {}
    count = 0

    def next_id() -> str:
        nonlocal count
        count += 1
        return f"c{count}"

    # ---- 1. the chosen takes in script order, each run of neighbouring lines as one clip
    for chain in result["clips"]:
        aid = chain["asset_id"]
        a, ws = assets[aid], transcripts[aid]
        length = engine._length(a)  # noqa: SLF001
        in_ms, out_ms = bounds(ws, chain["i0"], chain["i1"], length)
        takes: dict[str, dict] = {}
        for n in chain["lines"]:
            t = line_of[n]["take"]
            t_in, t_out = bounds(ws, t["i0"], t["i1"], length)
            takes[str(n)] = {"in_ms": max(in_ms, t_in), "out_ms": min(out_ms, t_out), "coverage": t["coverage"],
                             "quality": t["quality"]}
        cid = next_id()
        clip = {"id": cid, "asset_id": aid, "kind": "video", "in_ms": in_ms, "out_ms": out_ms,
                "label": a["filename"], "gain_db": 0.0, "include": True,
                "take_of": {"lines": list(chain["lines"]), "takes": takes}}
        prev = next((c for c in reversed(clips) if c.get("include", True)), None)
        if prev is not None and prev["asset_id"] == aid:  # a jump inside one recording: a straight cut, no click
            clip.update(join="cut", fade_in_ms=smart_edit.FADE_MS)
            prev["fade_out_ms"] = smart_edit.FADE_MS
        clips.append(clip)
        first, last = chain["lines"][0], chain["lines"][-1]
        which = f"Line {first}" if first == last else f"Lines {first} to {last}"
        said = " ".join(text_of.get(n, "") for n in chain["lines"])[:140]
        partly = [n for n in chain["lines"] if line_of[n]["status"] == "weak"]
        outline.append({"clip_id": cid, "label": a["filename"], "duration": round((out_ms - in_ms) / 1000, 1),
                        "summary": f"{which}: {said}" + (f" (line {partly[0]} only partly)" if len(partly) == 1 else
                                                           f" (lines {', '.join(map(str, partly))} only partly)"
                                                           if partly else "")})
        for n in chain["lines"]:
            clip_of_line[n] = cid
            for alt in line_of[n]["takes"]:
                aw = transcripts[alt["asset_id"]]
                a_in, a_out = bounds(aw, alt["i0"], alt["i1"], engine._length(assets[alt["asset_id"]]))  # noqa: SLF001
                alt_id = next_id()
                clips.append({"id": alt_id, "asset_id": alt["asset_id"], "kind": "video", "in_ms": a_in,
                              "out_ms": a_out, "label": assets[alt["asset_id"]]["filename"], "gain_db": 0.0,
                              "include": False, "take_of": {"line": n, "coverage": alt["coverage"],
                                                            "quality": alt["quality"]}})
                outline.append({"clip_id": alt_id, "label": assets[alt["asset_id"]]["filename"],
                                "duration": round((a_out - a_in) / 1000, 1),
                                "summary": f"Another take of line {n} ({round(alt['coverage'] * 100)}% of the line, "
                                           f"{quality_words(alt['quality'])}): {alt['said'][:120]}"})
                takes_of_line.setdefault(n, []).append({"clip_id": alt_id, "coverage": alt["coverage"],
                                                        "quality": alt["quality"]})
    # ---- 2. what was said but is not in the script (no take of any line, chosen or not): at the end, switched
    # off, where Put back finds it
    for aid in videos:
        ws = transcripts.get(aid) or []
        covered = bytearray(len(ws))
        for m in result["lines"]:
            for t in ([m["take"]] if m["take"] else []) + list(m["takes"]):
                if t["asset_id"] == aid:
                    covered[t["i0"]:t["i1"] + 1] = b"\x01" * (t["i1"] - t["i0"] + 1)
        for i0, i1 in script_mod._unused(covered) if ws else []:  # noqa: SLF001
            o_in, o_out = bounds(ws, i0, i1, engine._length(assets[aid]))  # noqa: SLF001
            oid = next_id()
            said = " ".join(str(w["w"]).strip() for w in ws[i0:i1 + 1])[:140]
            clips.append({"id": oid, "asset_id": aid, "kind": "video", "in_ms": o_in, "out_ms": o_out,
                          "label": assets[aid]["filename"], "gain_db": 0.0, "include": False,
                          "take_of": {"off_script": True}})
            outline.append({"clip_id": oid, "label": assets[aid]["filename"],
                            "duration": round((o_out - o_in) / 1000, 1), "summary": f"Not in the script: {said}"})
    if not any(c["include"] for c in clips):  # nothing of the script was found: the recordings play as they are
        whole: list[dict] = []
        rows: list[dict] = []
        for aid in videos:
            length = engine._length(assets[aid])  # noqa: SLF001
            cid = next_id()
            whole.append({"id": cid, "asset_id": aid, "kind": "video", "in_ms": 0, "out_ms": length,
                          "label": assets[aid]["filename"], "gain_db": 0.0, "include": True})
            rows.append({"clip_id": cid, "label": assets[aid]["filename"], "duration": round(length / 1000, 1),
                         "summary": "The whole recording (no line of the script was found in it)"})
        clips[0:0] = whole
        outline[0:0] = rows
        notes.append("No line of the script was found, so the recordings play whole, in the order of your media.")
    images = [assets[aid] for aid in project["asset_ids"] if (assets.get(aid) or {}).get("kind") == "image"]
    plan = smart_edit.plan_skeleton(project, values, assets, clips, outline, notes, t_type, t_ms)
    # ---- 3. pictures over the video, music and effects, as in any smart edit
    if images and opts["broll"] and transcripts:
        talks = [{"asset": assets[aid], "words": transcripts[aid], "sents": build_sentences(transcripts[aid]),
                  "status": [], "why": [], "scores": []} for aid in videos if aid in transcripts]
        table = smart_edit.sentence_table(project, assets, words)
        smart_edit._place_pictures(plan, images, talks, {}, table, feel, stats)  # noqa: SLF001
        shown = stats["overlays"]
        if shown:
            notes.append(f"Showed {shown} of your {len(images)} image{'s' if len(images) != 1 else ''} over the video "
                         "while the talking goes on.")
    elif images:
        for a in images:
            cid = next_id()
            plan["clips"].append({"id": cid, "asset_id": a["id"], "kind": "image", "in_ms": 0,
                                  "out_ms": smart_edit.OVERLAY_MS["balanced"], "label": a["filename"], "gain_db": 0.0,
                                  "include": True})
            plan["outline"].append({"clip_id": cid, "label": a["filename"], "summary": "Your image",
                                    "duration": smart_edit.OVERLAY_MS["balanced"] / 1000})
    smart_edit.add_sound(plan, assets, values, ctx, opts, feel, stats, notes)
    plan["chapters"] = chapters(lines, line_of, clips)
    plan["script"] = {"filename": script.get("filename") or "", "stats": result["stats"],
                      "lines": [{"n": m["n"], "status": m["status"], "coverage": m["coverage"],
                                 "clip_id": clip_of_line.get(m["n"], ""), "takes": takes_of_line.get(m["n"], [])}
                                for m in result["lines"]]}
    plan["smart"] = {"level": opts["level"], "options": opts, "script": True, "stats": stats,
                     "ai": {"used": False, "problem": "the script decides what plays"}, "picture_queries": []}
    if ctx.get("library_problem"):
        notes.append(f"Music or sound effects could not be made ({ctx['library_problem']}).")
    return plan


def chapters(lines: list[dict], line_of: dict[int, dict], clips: list[dict]) -> list[dict]:
    """A chapter at each script heading: where the first line after it that plays begins."""
    by_id = {c["id"]: c for c in clips}
    out: list[dict] = []
    seen: set[tuple[str, int]] = set()
    pending: str | None = None
    for ln in lines:
        if ln.get("kind") == "heading":
            pending = ln["text"].strip()[:60]
            continue
        if pending is None or ln.get("kind") != "line":
            continue
        m = line_of.get(ln["n"])
        clip = next((c for c in clips if c.get("include", True) and str(ln["n"]) in
                     ((c.get("take_of") or {}).get("takes") or {})), None) if m and m.get("take") else None
        if clip is None:
            continue
        offset = max(0, clip["take_of"]["takes"][str(ln["n"])]["in_ms"] - clip["in_ms"])
        key = (clip["id"], offset)
        if key not in seen and by_id.get(clip["id"]):
            seen.add(key)
            out.append({"clip_id": clip["id"], "offset_ms": offset, "title": pending})
        pending = None
    return out
