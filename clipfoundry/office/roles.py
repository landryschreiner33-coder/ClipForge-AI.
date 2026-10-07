"""The robot office's cast: one Director (COMMAND), eight section managers and sixteen workers, plus the Brain Core.

A role is a responsibility over the real job system (autopilot/queue.py), not a separate process or AI session. This
registry is the one place that says which role does which job kind and stage, which department and room it belongs to
and who its manager is. The frontend draws each role from its own sprite registry (frontend/src/office/cast.ts);
tests/test_office.py checks that both list exactly the same 25 identities.
"""
from __future__ import annotations

# rooms of the office (image A): departments plus the shared spaces
ROOMS = {
    "lounge": "Lounge", "boss": "Boss Hub", "brain": "Brain Room", "discover": "Discover", "analyze": "Analyze",
    "studio": "Clip Studio", "caption": "Caption", "workspace": "Team Workspace", "schedule": "Schedule",
    "dock": "Upload Dock", "system": "System",
}

DEPARTMENTS = {
    "discover": {"name": "Discover", "manager": "tracker", "accent": "lime"},
    "analyze": {"name": "Analyze", "manager": "vector", "accent": "cobalt"},
    "studio": {"name": "Clip Studio", "manager": "frame", "accent": "magenta"},
    "caption": {"name": "Caption", "manager": "script", "accent": "violet"},
    "schedule": {"name": "Schedule", "manager": "clock", "accent": "orange"},
    "dock": {"name": "Upload Dock", "manager": "harbor", "accent": "emerald"},
    "system": {"name": "System", "manager": "switch", "accent": "amber"},
    "brain": {"name": "Brain Room", "manager": "curator", "accent": "lavender"},
}


def _r(rid: str, name: str, rank: str, dept: str, title: str, job: str, **kw: object) -> dict:
    return {"id": rid, "name": name, "rank": rank, "department": dept, "room": kw.pop("room", dept), "title": title,
            "job": job, "manager": kw.pop("manager", "command" if rank == "manager" else
                                           (DEPARTMENTS[dept]["manager"] if rank == "worker" else "")), **kw}


ROLES: list[dict] = [
    _r("command", "COMMAND", "director", "boss", "Director",
       "Sets priorities, reads the managers' reports and records the decisions at four checkpoints: which videos to "
       "use, which clips to keep, whether a finished file passes, and whether it may be uploaded."),
    # ---- section managers
    _r("tracker", "TRACKER", "manager", "discover", "Discovery Manager",
       "Watches the searches, checks the videos they find and reports the best candidates."),
    _r("vector", "VECTOR", "manager", "analyze", "Analysis Manager",
       "Compares trend, source and clip-potential evidence and reports which source is worth processing."),
    _r("frame", "FRAME", "manager", "studio", "Clip Studio Manager",
       "Follows moment finding, story checks and rendering, and signs off the rendered clips."),
    _r("script", "SCRIPT", "manager", "caption", "Caption Manager",
       "Checks the captions and post text, and sends a clip back when a real problem is found."),
    _r("clock", "CLOCK", "manager", "schedule", "Schedule Manager",
       "Owns the schedule: plans posts into slots, moves missed ones and dispatches uploads at their time."),
    _r("harbor", "HARBOR", "manager", "dock", "Publish Manager",
       "Confirms that each upload goes only to the audience you chose, then signals the publisher."),
    _r("switch", "SWITCH", "manager", "system", "System Manager",
       "Watches the final quality check and the system's health, and reports recovery only after it is verified."),
    _r("curator", "CURATOR", "manager", "brain", "Learning Manager",
       "Reviews the results evidence and accepts a strategy change only when there is enough of it."),
    # ---- workers
    _r("radar", "RADAR", "worker", "discover", "Scout",
       "Runs the searches (YouTube, the web, the free-license library, your folders and feeds) and live checks.",
       kinds=("source_scout", "feed_scan", "live_watch"), stages={"trend_scan": ("youtube", "web", "library", "feeds")}),
    _r("archive", "ARCHIVE", "worker", "discover", "Researcher",
       "Gathers a source's context: reads pasted links, records live streams and transcribes the video.",
       kinds=("identify_link", "live_capture"), stages={"hunt_source": ("transcribe",), "live_capture": ("live",)}),
    _r("pulse", "PULSE", "worker", "analyze", "Trend Analyst",
       "Measures trend momentum from timestamped observations.", stages={"trend_scan": ("score",)}),
    _r("gavel", "GAVEL", "worker", "analyze", "Source Judge",
       "Checks whether a source may be processed and posted (rights, agreements, blocks) and stamps the decision.",
       kinds=("rights_check",)),
    _r("boost", "BOOST", "worker", "analyze", "Viral Analyst",
       "Scores the candidate moments' short-form potential (labeled estimates, never platform numbers).",
       kinds=("analyze_source",), stages={"analyze_source": ("analyze",)}),
    _r("spark", "SPARK", "worker", "studio", "Moment Finder",
       "Finds the complete moments in the transcript and marks their timestamps.",
       kinds=("hunt_source", "post_live"), stages={"hunt_source": ("candidates",)}),
    _r("story", "STORY", "worker", "studio", "Story Editor",
       "Checks each moment's hook, context and payoff and writes the clip's plan (its blueprint).",
       stages={"analyze_source": ("plan",)}),
    _r("splice", "SPLICE", "worker", "studio", "Video Editor",
       "Reframes and renders the 9:16 clips on the GPU.",
       kinds=("regenerate_clip",), stages={"analyze_source": ("render",), "regenerate_clip": ("render",)}),
    _r("glyph", "GLYPH", "worker", "caption", "Caption Agent",
       "Lays out the spoken words as timed captions.", stages={"analyze_source": ("captions",)}),
    _r("quill", "QUILL", "worker", "caption", "Title Agent",
       "Drafts the titles, descriptions and hashtags from words said in the clip.", kinds=("package_clip",)),
    _r("check", "CHECK", "worker", "system", "Quality Control",
       "Checks the exact rendered file (picture, sound, captions, cuts, text) and records pass or fail.",
       kinds=("quality_check",), stages={"quality_check": ("quality",)}),
    _r("lock", "LOCK", "worker", "dock", "Audience Verification",
       "Checks the destination account and that the upload is only for the audience you chose.",
       stages={"publish": ("audience",)}),
    _r("dock", "DOCK", "worker", "dock", "Publisher",
       "Uploads eligible clips, or hands you a ready-to-post package where the platform needs your own step.",
       kinds=("publish",), stages={"publish": ("upload",)}),
    _r("metric", "METRIC", "worker", "brain", "Analytics Agent",
       "Collects real result snapshots (platform numbers, your imports, tester feedback) with their time.",
       stages={"learn": ("refresh",)}),
    _r("synapse", "SYNAPSE", "worker", "brain", "Learning Agent",
       "Compares the results and proposes a strategy change to the Learning Manager.",
       kinds=("learn",), stages={"learn": ("evaluate",)}),
    _r("patch", "PATCH", "worker", "system", "System Guardian",
       "Runs the health checks and the maintenance that recovers stopped work.", kinds=("maintenance", "selftest")),
]
# schedule_tick belongs to CLOCK itself: the Schedule department has no worker (none is invented to fill a chair)
MANAGER_KINDS = {"clock": ("schedule_tick",), "tracker": ("trend_scan",)}

CORE = {"id": "core", "name": "CORE", "title": "Brain Core", "room": "brain",
        "job": "Memory and strategy settings. It cannot override privacy, credentials, cost limits, stop controls or "
               "the safety checks."}

BY_ID = {r["id"]: r for r in ROLES}


def role_for(kind: str, stage: str = "") -> str:
    """The role doing a job of this kind at this stage (the most specific match wins)."""
    if stage:
        for r in ROLES:
            if stage in (r.get("stages") or {}).get(kind, ()):
                return r["id"]
    for r in ROLES:
        if kind in (r.get("kinds") or ()):
            return r["id"]
    for rid, kinds in MANAGER_KINDS.items():
        if kind in kinds:
            return rid
    return "patch"  # anything unmapped is system work


def department_of(role_id: str) -> str:
    return BY_ID[role_id]["department"] if role_id in BY_ID else "system"


def manager_of(role_id: str) -> str:
    r = BY_ID.get(role_id) or {}
    return r.get("manager") or ("command" if r.get("rank") == "manager" else "")


def public() -> list[dict]:
    """The roster as the Team view shows it (stable order: Director, managers, workers)."""
    return [{k: v for k, v in r.items() if k not in ("kinds", "stages")} for r in ROLES]


def validate() -> list[str]:
    """Problems with the registry: exactly one Director, eight named managers, sixteen named workers."""
    problems = []
    ranks = [r["rank"] for r in ROLES]
    if ranks.count("director") != 1 or ranks.count("manager") != 8 or ranks.count("worker") != 16:
        problems.append(f"expected 1+8+16 roles, found {ranks.count('director')}+{ranks.count('manager')}+"
                        f"{ranks.count('worker')}")
    names = [r["name"] for r in ROLES]
    if len(set(names)) != len(names) or len(BY_ID) != len(ROLES):
        problems.append("role names and ids must be unique")
    for d, info in DEPARTMENTS.items():
        if BY_ID.get(info["manager"], {}).get("rank") != "manager" or BY_ID[info["manager"]]["department"] != d:
            problems.append(f"department {d} has no matching manager")
    for r in ROLES:
        if r["rank"] == "worker" and BY_ID.get(r["manager"], {}).get("rank") != "manager":
            problems.append(f"{r['name']} has no manager")
        if r["room"] not in ROOMS:
            problems.append(f"{r['name']} is in an unknown room")
    if CORE["id"] in BY_ID:
        problems.append("CORE is an object, not a 26th robot")
    return problems
