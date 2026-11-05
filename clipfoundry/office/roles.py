"""The robot office's cast: one Director, eight department managers and sixteen workers, plus the Brain Core.

A role is a responsibility over real work, not a separate process or AI session: the owner's own projects (Make clips,
Make a YouTube video, Find media, example videos) and Autopilot's jobs on submitted videos. This registry is the one
place that says which role does which kind of work and stage, which department and room it belongs to and who its
manager is. The rooms follow the real workflow (studio upgrade handoff, section 4): Intake, Media research, Story &
analysis, Editing, Sound & captions, Brain, Quality & export, Publishing, the Control room and the Lounge.

Role ids never change (custom robot names, office history and tests refer to them); titles and rooms moved when
automatic discovery was retired. The frontend draws each role from its own sprite registry
(frontend/src/office/cast.ts); tests/test_office.py checks that both list exactly the same 25 identities.
"""
from __future__ import annotations

ROOMS = {
    "lounge": "Lounge", "control": "Control room", "research": "Media research", "brain": "Brain",
    "intake": "Intake", "story": "Story & analysis", "editing": "Editing", "quality": "Quality & export",
    "sound": "Sound & captions", "publishing": "Publishing",
}
# Room ids used before the rooms followed the workflow (kept so an old address or event still finds its room).
OLD_ROOMS = {"boss": "control", "workspace": "research", "discover": "intake", "analyze": "story",
             "studio": "editing", "caption": "sound", "schedule": "publishing", "dock": "publishing",
             "system": "quality"}

DEPARTMENTS = {
    "intake": {"name": "Intake", "manager": "tracker", "accent": "lime",
               "does": "Your files and links: uploads, checks, reading and indexing."},
    "research": {"name": "Media research", "manager": "clock", "accent": "orange",
                 "does": "Media you search for in Find media, with source and license records and managed downloads."},
    "story": {"name": "Story & analysis", "manager": "vector", "accent": "cobalt",
              "does": "Transcripts, highlights, complete stories and their boundaries."},
    "editing": {"name": "Editing", "manager": "frame", "accent": "magenta",
                "does": "Assembly, framing, the sequence, transitions and previews."},
    "sound": {"name": "Sound & captions", "manager": "script", "accent": "violet",
              "does": "Captions and their timing, and the sound mix under them."},
    "brain": {"name": "Brain", "manager": "curator", "accent": "lavender",
              "does": "Guidance from your styles, skills and examples, and the choices it applied."},
    "quality": {"name": "Quality & export", "manager": "switch", "accent": "amber",
                "does": "Final renders and the checks on the finished file, sound and framing."},
    "publishing": {"name": "Publishing", "manager": "harbor", "accent": "emerald",
                   "does": "Review, scheduling, uploads and checking what the platform reports."},
}


def _r(rid: str, name: str, rank: str, dept: str, title: str, job: str, **kw: object) -> dict:
    return {"id": rid, "name": name, "rank": rank, "department": dept, "room": kw.pop("room", dept), "title": title,
            "job": job, "manager": kw.pop("manager", "command" if rank == "manager" else
                                           (DEPARTMENTS[dept]["manager"] if rank == "worker" else "")), **kw}


# Owner-started work reaches the office as these kinds (office/work.py): a Make clips project at its pipeline stage
# ("project"), a clip or version render, the studio's durable jobs (studio/jobs.py handlers) and an editor request
# waiting for the AI service. Autopilot's queue kinds (autopilot/queue.py) are listed next to them.
ROLES: list[dict] = [
    _r("command", "COMMAND", "director", "control", "Director",
       "Coordinates the departments, reads the managers' reports and records the decisions at the checkpoints: which "
       "videos to use, which clips to keep, whether a finished file passes, and whether it may be uploaded."),
    # ---- department managers
    _r("tracker", "TRACKER", "manager", "intake", "Intake Manager",
       "Receives your files and links, makes sure each one can be used and hands the project on."),
    _r("clock", "CLOCK", "manager", "research", "Media Research Manager",
       "Oversees the searches you ask for in Find media and keeps every file's source and license on record."),
    _r("vector", "VECTOR", "manager", "story", "Story & Analysis Manager",
       "Follows transcription, moment finding and story checks, and reports which moments make complete clips."),
    _r("frame", "FRAME", "manager", "editing", "Editing Manager",
       "Follows the rough cut, the sequence and the previews, and signs off the edit."),
    _r("script", "SCRIPT", "manager", "sound", "Sound & Captions Manager",
       "Reads the captions and checks the sound under them, and sends work back when something is wrong."),
    _r("curator", "CURATOR", "manager", "brain", "Brain Manager",
       "Looks up the guidance a project uses, settles conflicts in the order you set, and records what was applied."),
    _r("switch", "SWITCH", "manager", "quality", "Quality & Export Manager",
       "Watches the final renders and checks, and the system's health, and reports recovery only once verified."),
    _r("harbor", "HARBOR", "manager", "publishing", "Publishing Manager",
       "Owns review, the schedule and uploads: each post goes only to the account and audience you chose."),
    # ---- workers
    _r("radar", "RADAR", "worker", "intake", "Intake Clerk",
       "Takes in your uploads, links and live recordings, reads each file and indexes it.",
       kinds=("project", "link_import", "video_media", "identify_link", "live_watch", "live_capture",
              "source_scout", "feed_scan"),
       stages={"project": ("queued", "download", "probe"), "trend_scan": ("youtube", "web", "library", "feeds"),
               "live_capture": ("live",)}),
    _r("gavel", "GAVEL", "worker", "intake", "Rights Checker",
       "Checks your reuse statement and agreements for a video before it is processed or posted, and stamps the "
       "decision.", kinds=("rights_check",)),
    _r("pulse", "PULSE", "worker", "research", "Media Researcher",
       "Searches the media sources you allow and downloads the files you pick, with their license records.",
       kinds=("media_import", "media_suggest"), stages={"trend_scan": ("score",)}),
    _r("archive", "ARCHIVE", "worker", "story", "Transcriber",
       "Turns speech into timed words, for the moments, the stories and the captions.",
       stages={"project": ("audio", "transcribe"), "hunt_source": ("transcribe",)}),
    _r("spark", "SPARK", "worker", "story", "Moment Finder",
       "Finds the complete moments and stories in the transcript and marks their boundaries.",
       kinds=("hunt_source", "post_live"), stages={"project": ("candidates",), "hunt_source": ("candidates",)}),
    _r("boost", "BOOST", "worker", "story", "Moment Scorer",
       "Scores how strong each moment is (estimates, labeled as such) and measures example videos.",
       kinds=("analyze_source", "reference_analysis"), stages={"project": ("scoring",),
                                                              "analyze_source": ("analyze",)}),
    _r("story", "STORY", "worker", "editing", "Story Editor",
       "Builds the rough cut and each clip's plan: hook, context and payoff in order.",
       kinds=("video_build", "edit_request"), stages={"analyze_source": ("plan",), "regenerate_clip": ("plan",)}),
    _r("splice", "SPLICE", "worker", "editing", "Video Editor",
       "Frames and renders the clips and previews, and reports measured progress.",
       kinds=("regenerate_clip", "video_preview", "clip_render", "version_render"),
       stages={"project": ("render",), "analyze_source": ("render",), "regenerate_clip": ("render",)}),
    _r("glyph", "GLYPH", "worker", "sound", "Caption Agent",
       "Lays out the spoken words as timed captions and keeps them in sync with the sound.",
       stages={"analyze_source": ("captions",), "regenerate_clip": ("captions",)}),
    _r("metric", "METRIC", "worker", "brain", "Analytics Agent",
       "Collects real result readings (platform numbers, your imports, tester feedback) with their time.",
       stages={"learn": ("refresh",)}),
    _r("synapse", "SYNAPSE", "worker", "brain", "Learning Agent",
       "Compares results and proposes a strategy change to the Brain Manager.",
       kinds=("learn",), stages={"learn": ("evaluate",)}),
    _r("check", "CHECK", "worker", "quality", "Export & Quality Control",
       "Renders the final file and checks it (picture, sound, captions, cuts, text) before it can pass.",
       kinds=("quality_check", "video_render"), stages={"quality_check": ("quality",)}),
    _r("patch", "PATCH", "worker", "quality", "System Guardian",
       "Runs the health checks and the maintenance that recovers stopped work.", kinds=("maintenance", "selftest")),
    _r("quill", "QUILL", "worker", "publishing", "Post Writer",
       "Drafts the title, description and hashtags from words said in the clip.", kinds=("package_clip",)),
    _r("lock", "LOCK", "worker", "publishing", "Audience Verification",
       "Checks the destination account and that the upload is only for the audience you chose.",
       stages={"publish": ("audience",)}),
    _r("dock", "DOCK", "worker", "publishing", "Publisher",
       "Uploads eligible clips, or hands you a ready-to-post package where the platform needs your own step.",
       kinds=("publish",), stages={"publish": ("upload",)}),
]
# Recurring passes that belong to a manager itself (no worker is invented to fill a chair): Publishing plans the
# schedule, and Intake owns the retired discovery pass (it runs only if discovery is turned back on).
MANAGER_KINDS = {"harbor": ("schedule_tick",), "tracker": ("trend_scan",)}

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
    return "patch"  # anything unmapped is system work (Quality & export)


def department_of(role_id: str) -> str:
    return BY_ID[role_id]["department"] if role_id in BY_ID else "quality"


def manager_of(role_id: str) -> str:
    r = BY_ID.get(role_id) or {}
    return r.get("manager") or ("command" if r.get("rank") == "manager" else "")


def handoff_path(*role_ids: str) -> list[str]:
    """Known recipients in order, with repeated adjacent seats removed. Never invent a missing role."""
    path: list[str] = []
    for role_id in role_ids:
        if role_id in BY_ID and (not path or path[-1] != role_id):
            path.append(role_id)
    return path


def reporting_path(role_id: str) -> list[str]:
    """A recorded worker report goes through its own manager before reaching the Director."""
    if role_id not in BY_ID:
        return []
    return handoff_path(role_id, manager_of(role_id), "command")


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
