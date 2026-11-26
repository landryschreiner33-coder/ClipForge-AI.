"""What ClipForge AI saw and heard in one video, in one place (docs/clipforge/WATCH_AND_LISTEN.md).

Three sources, each optional:

* heard (listen.py): every sound named, every 0.48 s of the whole track;
* watched (watch.py): every sampled frame measured (movement, cuts, faces, light);
* seen (eyes.describe_video): what the built-in model says happens in each part of the video.

This module turns them into what clip picking and ClipForge AI read: anchors for new candidate clips (a laugh, a
cheer, an explosion, a burst of action: places a clip should end on or contain), a bounded and explained part of
each clip's score, a few words per line of transcript for the model that reads it, and plain lines for answers
about a clip or a moment. Without any of the three, everything here returns nothing and clip picking is as before.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import listen, watch
from .common import read_json

REACTION_WORDS = {"laughter": "laughter", "applause": "applause", "cheering": "cheering",
                  "screaming": "screaming or shouting", "gasp": "a gasp"}
HEARD_WEIGHT = 5.0         # the most what is heard can move a Clip Score
WATCHED_WEIGHT = 3.0       # ... what is measured in the picture
SEEN_WEIGHT = 4.0          # ... what the model says happens
TOTAL_WEIGHT = 9.0         # all three together
ANCHOR_LIMIT = 24          # new candidate clips made from what was seen and heard, at most
TALK_LOW = 0.5             # a clip talked through less than this share of its time says less with its words ...
SHOW_WEIGHT = 0.5          # ... so its score moves this far toward what happens in it (at no talk at all) ...
SHOW_MAX = 12.0            # ... by at most this many points
SEEN_NOTE_CHARS = 110


@dataclass
class Senses:
    heard: "listen.Heard | None" = None
    watched: "watch.Watched | None" = None
    seen: list[dict] = field(default_factory=list)       # eyes.describe_video parts, in time order
    seen_notes: dict = field(default_factory=dict)       # how the describing went (asked, answered, coverage ...)

    # -------------------------------------------------- loading
    @staticmethod
    def files(pdir: Path) -> dict[str, Path]:
        return {"heard": pdir / "sounds.json", "watched": pdir / "watch.json", "seen": pdir / "seen.json"}

    @staticmethod
    def load(pdir: Path) -> "Senses":
        f = Senses.files(pdir)
        seen = read_json(f["seen"], {}) or {}
        return Senses(listen.load(f["heard"]) if f["heard"].is_file() else None,
                      watch.load(f["watched"]) if f["watched"].is_file() else None,
                      [p for p in (seen.get("parts") or []) if isinstance(p, dict)])

    def any(self) -> bool:
        return bool(self.heard is not None or self.watched is not None or self.seen)

    @staticmethod
    def status(settings: dict) -> dict:
        """What Settings → ClipForge AI shows: each sense on or off, and why one cannot run here."""
        from . import eyes

        on = listen.enabled(settings)
        return {"listen": {"on": on, "usable": bool(on and listen.usable(settings)),
                           "problem": listen.problem() if on else "", "name": "YAMNet", "license": "Apache-2.0",
                           "bytes": listen.MODEL.stat().st_size if listen.MODEL.is_file() else 0,
                           "classes": len(listen.class_names()) if listen.CLASS_MAP.is_file() else 0},
                "watch": {"on": watch.enabled(settings), "fps": [watch.fps_for(60), watch.fps_for(30 * 60),
                                                                watch.fps_for(120 * 60)]},
                "describe": {"on": eyes.describe_configured(settings), "builtin": settings.get("ai_provider") == "builtin",
                             "eyes": bool(settings.get("ai_eyes", True)),
                             "budget_s": float(settings.get("ai_watch_budget_s") or 0)}}

    # -------------------------------------------------- reading a stretch
    def seen_in(self, t0: float, t1: float) -> list[dict]:
        return [p for p in self.seen if p["end"] > t0 + 0.2 and p["start"] < t1 - 0.2]

    def seen_lines(self, t0: float, t1: float, limit: int = 6, rel: bool = True) -> list[str]:
        """What the model saw in [t0, t1], one line per part (repeats of the part before left out)."""
        out, last = [], ""
        for p in self.seen_in(t0, t1):
            if p.get("what") == last:
                continue
            last = p.get("what") or ""
            at = max(0.0, p["start"] - t0) if rel else p["start"]
            out.append(f"{listen.stamp(at)} {last}")
        return out[:limit]

    def heard_lines(self, t0: float, t1: float, limit: int = 8, rel: bool = True) -> list[str]:
        if self.heard is None:
            return []
        out = []
        for e in self.heard.events_in(t0, t1, listen.NOTE_KINDS):
            at = max(0.0, e["start"] - t0) if rel else e["start"]
            word = listen.WORDS[e["kind"]]
            if out and out[-1].endswith(word):
                continue
            out.append(f"{listen.stamp(at)} {word}")
        music = self.heard.share("music", t0, t1)
        if music >= 0.3:
            out.append(f"music under {round(100 * music)}% of it")
        return out[:limit]

    def note(self, t0: float, t1: float, last_seen: str = "") -> tuple[str, str]:
        """(note, seen words) for a line of transcript from t0 to t1: what is seen there when it is new, and what is
        heard around it (also in the pause after it, where reactions come). Empty when there is nothing to add."""
        bits = []
        seen = ""
        parts = self.seen_in(t0, t1)
        if parts:
            mid = (t0 + t1) / 2
            p = min(parts, key=lambda q: abs((q["start"] + q["end"]) / 2 - mid))
            seen = p.get("what") or ""
            if seen and seen != last_seen:
                bits.append("seen: " + seen[:SEEN_NOTE_CHARS])
        if self.heard is not None:
            h = self.heard.note(t0, t1 + 1.5)
            if h:
                bits.append("heard: " + h)
        return "; ".join(bits), seen or last_seen

    # -------------------------------------------------- scoring a clip
    def features(self, t0: float, t1: float) -> dict:
        out: dict = {}
        if self.heard is not None:
            out["heard"] = self.heard.features(t0, t1)
        if self.watched is not None:
            out["watched"] = self.watched.features(t0, t1)
        parts = self.seen_in(t0, t1)
        if parts:
            tags: dict[str, int] = {}
            for p in parts:
                for t in p.get("tags") or []:
                    tags[t] = tags.get(t, 0) + 1
            from .eyes import EXCITING_TAGS

            dur = max(0.1, t1 - t0)
            covered = sum(min(t1, p["end"]) - max(t0, p["start"]) for p in parts)
            out["seen"] = {"lines": self.seen_lines(t0, t1, 5), "tags": sorted(tags, key=lambda k: -tags[k])[:6],
                           "action": round(max(p.get("action", 0) for p in parts), 1),
                           "action_mean": round(sum(p.get("action", 0) * (min(t1, p["end"]) - max(t0, p["start"]))
                                                    for p in parts) / max(0.1, covered), 1),
                           "exciting": sorted({t for t in tags if t in EXCITING_TAGS}),
                           "nothing": round(sum(1 for p in parts if "nothing happens" in (p.get("tags") or []))
                                            / len(parts), 2),
                           "text": next((p["text"] for p in parts if p.get("text")), ""),
                           "coverage": round(min(1.0, covered / dur), 2)}
        return out

    def adjust(self, f: dict, base_action: float | None = None) -> tuple[float, list[str]]:
        """(points, reasons): what was seen and heard moves a Clip Score by at most ±TOTAL_WEIGHT, each part
        within its own bound and explained."""
        why: list[str] = []
        total = 0.0
        h = f.get("heard")
        if h:
            pts = 0.0
            reacts = [m for m in h.get("moments") or [] if m["kind"] in listen.REACTIONS]
            if h.get("ends_on_reaction"):
                pts += 2.5
            pts += min(2.0, 0.8 * len(reacts))
            pts += min(1.5, 0.6 * int(h.get("exciting") or 0))
            if h.get("opens_on_reaction"):
                pts -= 1.5     # the cause of the laugh or the cheer came before the clip
            if h.get("silence", 0) >= 0.4 and h.get("speech", 0) < 0.3:
                pts -= 2.0
            pts = max(-HEARD_WEIGHT, min(HEARD_WEIGHT, pts))
            if abs(pts) >= 0.5:
                kinds = sorted({REACTION_WORDS.get(m["kind"], listen.WORDS.get(m["kind"], m["kind"]))
                                for m in h.get("moments") or []
                                if m["kind"] in listen.REACTIONS or m["kind"] in listen.EXCITING})
                said = (", ".join(kinds[:3]) if kinds else ("mostly silence" if pts < 0 else "lively sound"))
                why.append(f"{pts:+.1f} ClipForge AI heard {said}" + (" at the end" if h.get("ends_on_reaction")
                                                                        else ""))
            total += pts
        w = f.get("watched")
        if w:
            ref = 0.3 if base_action is None else base_action
            pts = max(-WATCHED_WEIGHT, min(WATCHED_WEIGHT, 6.0 * (float(w.get("action", 0)) - ref)
                                           + 2.0 * (float(w.get("opening_action", 0)) - ref)))
            if w.get("still_share", 0) >= 0.6 and not w.get("face_share"):
                pts -= 2.0
            if w.get("dark_share", 0) >= 0.5:
                pts -= 1.0
            pts = max(-WATCHED_WEIGHT, min(WATCHED_WEIGHT, pts))
            if abs(pts) >= 0.5:
                why.append(f"{pts:+.1f} the picture " + ("moves and changes more than this video's usual"
                                                         if pts > 0 else "stands still or stays dark more than "
                                                                         "this video's usual"))
            total += pts
        s = f.get("seen")
        if s and s.get("coverage", 0) >= 0.3:
            pts = 0.5 * (float(s.get("action_mean", 0)) - 4.0) + 1.2 * min(2, len(s.get("exciting") or []))
            pts -= 3.0 * float(s.get("nothing", 0))
            pts = max(-SEEN_WEIGHT, min(SEEN_WEIGHT, pts))
            if abs(pts) >= 0.5:
                what = ", ".join(s.get("exciting") or []) or (s["lines"][0].split(" ", 1)[-1] if s.get("lines")
                                                             else "")
                why.append(f"{pts:+.1f} ClipForge AI watched it" + (f" ({what[:90]})" if what else ""))
            total += pts
        total = max(-TOTAL_WEIGHT, min(TOTAL_WEIGHT, total))
        return round(total, 1), why

    def show(self, f: dict, base_action: float | None = None) -> float | None:
        """0-100: how much happens in a clip by what was seen and heard alone (None without any sense). It speaks
        for clips where little is said, which a score built from their words underrates (a fight, a chase, a goal,
        a dance)."""
        if not f:
            return None
        x = 40.0
        h = f.get("heard")
        if h:
            reacts = [m for m in h.get("moments") or [] if m["kind"] in listen.REACTIONS]
            x += 12.0 if h.get("ends_on_reaction") else 0.0
            x += min(18.0, 6.0 * len(reacts)) + min(18.0, 6.0 * int(h.get("exciting") or 0))
            x -= 15.0 if h.get("silence", 0) >= 0.5 else 0.0
        w = f.get("watched")
        if w:
            ref = 0.3 if base_action is None else base_action
            x += max(-20.0, min(20.0, 40.0 * (float(w.get("action", 0)) - ref)))
            x += 8.0 if float(w.get("action_peak", 0)) >= 0.7 else 0.0
            x -= 15.0 if w.get("still_share", 0) >= 0.6 and not w.get("face_share") else 0.0
        s = f.get("seen")
        if s and s.get("coverage", 0) >= 0.3:
            x += max(-24.0, min(24.0, 4.0 * (float(s.get("action_mean", 0)) - 4.0)))
            x += min(12.0, 6.0 * len(s.get("exciting") or []))
            x -= 20.0 * float(s.get("nothing", 0))
        return round(max(0.0, min(100.0, x)), 1)

    def judge_clip(self, t0: float, t1: float, words: list[dict], score: float,
                   base_action: float | None = None, blend: bool = True) -> dict:
        """Everything the Clip Score takes from the senses for one clip: the features, the bounded adjustment and
        its reasons, and, when little is said, how far the score moves toward what happens in it (`show_adjust`,
        at most ±SHOW_MAX, with its own reason). `blend` False: the score already comes from what happens (a time
        window built around a moment, candidates._time_window), so it is not moved toward it twice."""
        f = self.features(t0, t1)
        pts, why = self.adjust(f, base_action)
        talk = talk_share(words, t0, t1)
        show = self.show(f, base_action)
        weight = SHOW_WEIGHT * max(0.0, (TALK_LOW - talk) / TALK_LOW) if blend else 0.0
        move = 0.0 if show is None else max(-SHOW_MAX, min(SHOW_MAX, weight * (show - float(score))))
        out = {**f, "adjust": pts, "why": why, "talk": round(talk, 2), "show": show, "show_adjust": round(move, 1)}
        if abs(move) >= 0.5:
            out["show_why"] = (f"{move:+.1f} little is said here ({round(100 * talk)}% of the time), so it is judged "
                               f"more on what happens in it ({show:.0f}/100 by what ClipForge AI saw and heard)")
        return out

    def base_action(self) -> float | None:
        if self.watched is None or not self.watched.n:
            return None
        return float(self.watched.action().mean())

    def interest(self, t0: float, t1: float) -> float:
        """0-1, cheap, for the fast filter: reactions and exciting sounds, action and the model's action."""
        x = 0.0
        if self.heard is not None:
            ev = self.heard.events_in(t0, t1 + 3.0)
            x += min(0.4, 0.15 * sum(1 for e in ev if e["kind"] in listen.REACTIONS))
            x += min(0.2, 0.07 * sum(1 for e in ev if e["kind"] in listen.EXCITING and e["start"] < t1))
        if self.watched is not None:
            a, b = self.watched._range(t0, t1)  # noqa: SLF001
            act = self.watched.action()[a:b]
            x += 0.2 * float(act.mean()) if len(act) else 0.0
        parts = self.seen_in(t0, t1)
        if parts:
            x += 0.2 * max(p.get("action", 0) for p in parts) / 10.0
        return max(0.0, min(1.0, x))

    # -------------------------------------------------- anchors for new candidates
    def anchors(self, limit: int = ANCHOR_LIMIT) -> list[dict]:
        """Moments a clip should be built around, strongest first: {at, kind, strength, why, end_after}.
        `end_after` = True for a reaction (the clip ends just after it; its cause comes before it)."""
        out: list[dict] = []
        if self.heard is not None:
            for e in self.heard.events:
                if e["kind"] in listen.REACTIONS:
                    out.append({"at": e["start"], "until": e["end"], "kind": e["kind"], "strength": e["peak"],
                                "end_after": True, "why": f"ClipForge AI heard {listen.WORDS[e['kind']]}"})
                elif e["kind"] in ("boom", "crash"):
                    out.append({"at": e["start"], "until": e["end"], "kind": e["kind"], "strength": 0.8 * e["peak"],
                                "end_after": False, "why": f"ClipForge AI heard {listen.WORDS[e['kind']]}"})
        if self.watched is not None:
            for m in self.watched.moments(limit=limit):
                out.append({"at": m["at"], "until": m["at"] + 1.0, "kind": "action", "strength": 0.7 * m["action"],
                            "end_after": False, "why": "the picture comes alive (movement and cuts)"})
        from .eyes import EXCITING_TAGS

        for p in self.seen:
            hot = [t for t in p.get("tags") or [] if t in EXCITING_TAGS]
            if p.get("action", 0) >= 7 or hot:
                out.append({"at": p["start"], "until": p["end"], "kind": "seen",
                            "strength": min(1.0, 0.1 * p.get("action", 0) + 0.15 * len(hot)), "end_after": False,
                            "why": f"ClipForge AI saw: {p.get('what', '')[:100]}"})
        out.sort(key=lambda a: -a["strength"])
        picked: list[dict] = []
        for a in out:
            if len(picked) >= limit:
                break
            if all(abs(a["at"] - b["at"]) >= 8.0 for b in picked):
                picked.append(a)
        return picked

    # -------------------------------------------------- for people and models
    def summary(self, t0: float, t1: float, rel: bool = True) -> dict:
        """Lines for the clip's "Why" and for ClipForge AI's answers: seen, heard, picture."""
        out: dict = {}
        seen = self.seen_lines(t0, t1, 6, rel)
        if seen:
            out["seen"] = seen
        heard = self.heard_lines(t0, t1, 8, rel)
        if heard:
            out["heard"] = heard
        if self.heard is not None:
            sounds = [n for n, _ in self.heard.top_sounds(t0, t1, 5)]
            if sounds:
                out["sounds"] = sounds
        if self.watched is not None:
            w = self.watched.features(t0, t1)
            bits = [f"{w['shots']} shot{'s' if w['shots'] != 1 else ''}"]
            if w["face_share"] >= 0.5:
                bits.append(f"a face on screen {round(100 * w['face_share'])}% of the time")
            if w["still_share"] >= 0.5:
                bits.append("the picture mostly stands still")
            elif w["action"] >= 0.45:
                bits.append("lots of movement")
            out["picture"] = ", ".join(bits)
        return out

    def describe(self, t0: float, t1: float, rel: bool = True) -> list[str]:
        s = self.summary(t0, t1, rel)
        lines = []
        if s.get("seen"):
            lines.append("Seen (by ClipForge AI): " + " | ".join(s["seen"]))
        if s.get("heard"):
            lines.append("Heard: " + ", ".join(s["heard"]))
        elif s.get("sounds"):
            lines.append("Sounds: " + ", ".join(s["sounds"]))
        if s.get("picture"):
            lines.append("Picture: " + s["picture"])
        return lines


def talk_share(words: list[dict], t0: float, t1: float) -> float:
    """The share of [t0, t1] during which a word is being said."""
    said = sum(max(0.0, min(t1, float(w["end"])) - max(t0, float(w["start"]))) for w in words
               if float(w["end"]) > t0 and float(w["start"]) < t1)
    return min(1.0, said / max(0.1, t1 - t0))
