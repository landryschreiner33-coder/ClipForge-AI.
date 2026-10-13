"""Read-only posting explanations. Running workers and rendered files do not prove a clip can be uploaded."""
from __future__ import annotations

from .. import db
from ..publish import audience
from . import autopublish, gate, rights, state

LIMIT = 200
ACTIVE_POSTS = ('awaiting_approval', 'approved', 'publishing', 'reconciling', 'action_needed')


def setup_needs(settings: dict, platforms: dict) -> list[dict]:
    """Derive setup holds during reads; a stalled scheduler cannot be the only writer of an audience warning."""
    if state.paused() or not settings.get('autopilot_enabled'):
        return []
    permission = autopublish.view(settings)
    finished = bool(db.scalar("SELECT COUNT(*) FROM clips WHERE status = 'ready' AND project_id IN "
                              "(SELECT id FROM projects WHERE origin IN ('autopilot', 'live'))"))
    items = []
    for platform, name in (('youtube', 'YouTube'), ('tiktok', 'TikTok')):
        account = platforms.get(platform) or {}
        if not settings.get(f'autopilot_{platform}') or not account.get('connected') or account.get('needs_reconnect'):
            continue
        dest = audience.destination(platform, settings)
        if dest['intent'] == audience.LOCAL_ONLY:
            continue
        if not dest['confirmed']:
            items.append({'key': f'audience_setup:{platform}', 'type': 'other',
                          'title': f'Choose who watches your {name} clips',
                          'detail': 'Finished clips cannot be scheduled until their audience is chosen and confirmed.',
                          'fix': 'Settings → Integrations → Who watches.', 'link': '#/settings/integrations'})
        elif platform == 'youtube' and finished and settings.get('autopilot_auto_publish') \
                and not permission[platform]['enabled']:
            items.append({'key': 'auto_publish_setup:youtube', 'type': 'other',
                          'title': 'YouTube automatic publishing is not enabled for new clips',
                          'detail': permission[platform].get('blocker') or
                          'Connecting YouTube does not authorize automatic uploads. '
                          'Give permission or approve each post.',
                          'fix': 'Missions → How posts go out → Turn on automatic publishing.', 'link': '#/missions'})
    return items


def view(settings: dict, platforms: dict, workers_alive: bool) -> dict:
    """Show where recent finished automatic clips stop, without scheduling, scanning folders or calling a platform."""
    where = "status = 'ready' AND project_id IN (SELECT id FROM projects WHERE origin IN ('autopilot', 'live'))"
    total = int(db.scalar(f"SELECT COUNT(*) FROM clips WHERE {where}") or 0)
    clips = db.select("clips", where, (), "created_at DESC", LIMIT)
    permission = autopublish.view(settings)
    out = []
    for platform, name in (("youtube", "YouTube"), ("tiktok", "TikTok")):
        account = platforms.get(platform) or {}
        if not account.get("connected"):
            continue  # A disconnected TikTok account cannot hold a YouTube-only setup.
        dest = audience.destination(platform, settings)
        counts = {k: 0 for k in ('local_only', 'preparing', 'checking', 'failed_check', 'ready',
                               'scheduled', 'review', 'problems', 'preparation_stopped', 'waiting_time')}
        marks = ','.join('?' * len(ACTIVE_POSTS))
        posts = db.select("scheduled_publications", f"platform = ? AND status IN ({marks})",
                          (platform, *ACTIVE_POSTS))
        counts['scheduled'] = sum(p['status'] in ('approved', 'publishing') and p.get('planned_at') is not None
                                  for p in posts)
        counts['waiting_time'] = sum(p['status'] == 'approved' and p.get('planned_at') is None for p in posts)
        counts['review'] = sum(p['status'] == 'awaiting_approval' for p in posts)
        counts['problems'] = sum(p['status'] in ('reconciling', 'action_needed') for p in posts)
        occupied = {p['clip_id'] for p in posts}
        done = {p['clip_id'] for p in db.select('scheduled_publications',
                "platform = ? AND status = 'published'", (platform,))}
        for clip in clips:
            if clip['id'] in occupied or clip['id'] in done:
                continue
            project = db.get_project(clip['project_id']) or {}
            source = db.fetch('sources', project.get('source_id') or '') if project.get('source_id') else None
            try:
                rights.gate(source, 'schedule', settings)
                allowed, _ = rights.platform_allowed(source, platform, settings)
            except rights.RightsBlocked:
                allowed = False
            if not allowed:
                counts['local_only'] += 1
                continue
            meta = db.select('metadata_candidates', 'clip_id = ? AND platform = ? AND selected = 1',
                             (clip['id'], platform), 'created_at DESC', 1)
            if not meta:
                jobs = db.select('worker_jobs', "kind = 'package_clip' AND (ref_id = ? OR "
                                 "json_extract(payload, '$.clip_id') = ?)", (clip['id'], clip['id']),
                                 'created_at DESC', 1)
                stopped = bool(jobs and jobs[0]['status'] in ('failed', 'canceled'))
                counts['preparation_stopped' if stopped else 'preparing'] += 1
                continue
            report = gate.report_for(clip)
            checked_text = (report or {}).get('metadata', {}).get(platform) or {}
            if not report or checked_text.get('metadata_id') != meta[0]['id']:
                counts['checking'] += 1
            elif report['status'] != 'passed' or checked_text.get('status') != 'passed':
                counts['failed_check'] += 1
            else:
                counts['ready'] += 1
        code, title, detail, link = _explanation(settings, platform, name, account, dest, permission[platform],
                                               counts, total, workers_alive)
        out.append({'platform': platform, 'code': code, 'title': title, 'detail': detail, 'link': link,
                    'counts': counts, 'automatic': bool(permission[platform]['enabled'])})
    return {'finished': total, 'checked': len(clips), 'sampled': total > LIMIT, 'platforms': out}


def _explanation(settings: dict, platform: str, name: str, account: dict, dest: dict, consent: dict,
                 counts: dict, total: int, alive: bool) -> tuple[str, str, str, str]:
    integrations, queue_link = "#/settings/integrations", "#/queue/review"
    if state.paused() or not settings.get("autopilot_enabled"):
        return ("paused", "Automatic work is paused",
                "Resume Autopilot to continue preparing and planning clips.", "#/missions")
    if account.get("needs_reconnect"):
        return ("account", f"{name} needs reconnection",
                "The saved sign-in needs to be renewed on this PC.", "#/settings")
    if not settings.get(f"autopilot_{platform}"):
        return ("platform_off", f"{name} is not used by Autopilot",
                "Turn on this destination under How posts go out.", "#/missions")
    if dest["intent"] == audience.LOCAL_ONLY:
        return "local_only", f"{name} uploads are off", "Who watches is set to Keep clips on this PC.", integrations
    if not dest["confirmed"]:
        return "audience", f"Choose who watches on {name}", (
            "Finished clips stay on this PC until you choose and confirm their audience in Settings → Integrations."
        ), integrations
    if not settings.get("autopilot_auto_schedule"):
        return "schedule_off", "Automatic scheduling is off", (
            "Finished clips are not assigned posting times. Turn on automatic scheduling in Settings → Advanced."
        ), "#/settings/advanced"
    if not alive:
        return ("workers", "Background work is not reporting",
                "Check Missions → Advanced → System on this PC.", "#/missions/system")
    if platform == "youtube" and not consent["enabled"]:
        message = consent.get("blocker") or (
            "Turn on automatic YouTube publishing, or approve each planned post yourself.")
        return "permission", "Automatic YouTube publishing is off for new clips", message, "#/missions"
    if settings.get("autopilot_publishing_paused"):
        return ("publishing_paused", "Publishing is paused",
                "Clips can still be made and scheduled; resume publishing on the Office.", "#/")
    if not settings.get("autopilot_auto_publish"):
        return ("publish_off", "Scheduled uploads are off",
                "Turn on publishing approved posts in Settings → Advanced.", "#/settings/advanced")
    if counts["review"]:
        return "review", "Planned posts need your approval", (
            "Review their exact files and audience in Queue. Permission for another channel or audience "
            "cannot approve them."
        ), queue_link
    if counts["problems"]:
        return ("problems", "Planned posts need attention",
                "Check the actual upload hold in Queue → Problems.", "#/queue/problems")
    if counts["waiting_time"]:
        return ("waiting_time", "Approved posts are waiting for a new posting time",
                "Check Queue for the current wait or platform limit. No posting time is confirmed yet.",
                "#/queue/scheduled")
    if counts["scheduled"]:
        return ("scheduled", "Posts have a schedule",
                "Queue shows their posting times and any upload holds.", "#/queue/scheduled")
    if int(settings.get(f"autopilot_{platform}_daily_limit") or 0) <= 0:
        return ("limit", f"{name} daily limit is zero",
                "Set a positive daily posting limit in Settings → Advanced.", "#/settings/advanced")
    if settings.get("autopilot_active_start") == settings.get("autopilot_active_end"):
        return ("window", "Posting hours leave no time to upload",
                "Choose a posting window in Settings → Defaults.", "#/settings/defaults")
    if counts["ready"]:
        return "planning", "Finished clips are waiting for a posting time", (
            "The scheduler checks available posting hours, daily limits and platform waits. "
            "Check Activity if this persists."
        ), "#/missions/activity"
    if counts["preparing"]:
        return "preparing", "Finished clips need titles and captions", (
            "Eligible interrupted handoffs recover automatically. Check Jobs for the current post-preparation step."
        ), "#/missions/jobs"
    if counts["checking"]:
        return "checking", "Finished clips are waiting for their final check", (
            "A rendered file alone is not ready to upload. File and text checks must pass first."
        ), "#/missions/jobs"
    if counts["preparation_stopped"]:
        return "preparation_stopped", "Post preparation stopped", (
            "Some finished clips have failed or canceled post preparation. Check Jobs. "
            "Canceled work stays stopped until you choose to retry it."
        ), "#/missions/jobs"
    if counts["failed_check"]:
        return "quality", "Finished clips did not pass the final check", (
            "Open their Final check details in Clips. Automatic repair runs only when it can safely fix the problem."
        ), "#/clips"
    if counts["local_only"]:
        return "rights", "Finished clips are for local use", (
            f"These videos have no recorded reuse permission for {name}. Add your original videos or record a valid "
            "creator agreement under Permissions & sources; being public does not grant permission."
        ), "#/missions/sources"
    if total:
        return ("waiting", "No new finished clip is ready to plan",
                "Recent clips are already planned, published or held. See Queue and Activity.", "#/queue")
    return ("rendering", "No finished automatic clips yet",
            "Autopilot needs usable video originals and strong moments before it can plan posts.", "#/missions/sources")
