"""Read-only posting explanations. Running workers and rendered files do not prove a clip can be uploaded."""
from __future__ import annotations

from .. import config, db
from ..publish import audience
from . import autopublish, gate, providers, rights, state

LIMIT = 200
ACTIVE_POSTS = ('awaiting_approval', 'approved', 'publishing', 'reconciling', 'action_needed')


def source_guidance(settings: dict) -> dict:
    """Fixed desktop guidance; no folder scan, remote request or automatic permission decision."""
    if not config.discovery_enabled(settings):
        return {'uploadable_only': False,
                'review_before_publish': bool(settings.get('autopilot_review_before_publish', True)),
                'title': 'Add a video link or file in Missions',
                'detail': 'Use Make & upload clips to authorize qualifying YouTube clips from that input. '
                          'Relevant supported Brain guidance shapes new clips, with Settings filling gaps. '
                          'Make clips only keeps them on this PC. Earlier posts keep their review requirements.',
                'options': [{'title': 'Add your video', 'detail': 'No search API key is needed.', 'link': '#/missions'}]}
    if settings.get('autopilot_review_before_publish', True):
        return {'uploadable_only': False, 'review_before_publish': True,
                'title': 'Automatic discovery prepares clips for your review',
                'detail': 'Accessible videos can be prepared and assigned a posting time even when reuse '
                          'permission is unrecorded. Nothing uploads until you check reuse, review the exact '
                          'clip and approve its post. Saved blocks, quality and file-access checks still apply.',
                'options': [{'title': 'Review planned posts',
                             'detail': 'Open each clip in Queue. If its reuse permission is unrecorded, '
                                       'confirm your permission and record its basis before approving.',
                             'link': '#/queue/review'}]}
    uploadable_only = providers.reusable_discovery_only(settings)
    return {'uploadable_only': uploadable_only,
            'title': 'Automatic discovery looks for videos it can post' if uploadable_only else
                     'Automatic discovery also makes local-only clips',
            'detail': ('New broad-search picks need recorded reuse coverage for an enabled destination. '
                       'Existing local-only clips stay on this PC until valid permission covers their originals.')
                      if uploadable_only else
                      ('Public finds can be clipped locally without permission to repost. '
                       'Enable Only find videos I can post to focus automatic work on uploads.'),
            'options': [
                {'title': 'Use your own originals',
                 'detail': 'Put videos you made or may reuse in Your videos folder. '
                           'Your connected YouTube channel is also checked; downloading still needs allowed access.',
                 'link': '#/missions/sources'},
                {'title': 'Record an existing creator agreement',
                 'detail': 'Add what the creator agreed to and the platforms it covers. '
                           'Use their original files or a permitted download; a public link is not permission.',
                 'link': '#/missions/sources'},
                {'title': 'Search verified free-license media',
                 'detail': 'Creative Commons YouTube searches and the free Wikimedia Commons library '
                           'use reported licenses. Quality, original-file access and attribution checks still apply.',
                 'link': '#/missions/sources'},
            ]}


def _submitted_upload_requested(settings: dict, platform: str) -> bool:
    """Display only: a current source request is independent of broad automation switches."""
    from . import submissions

    for request in db.select('source_submissions', "platform=? AND revoked_at IS NULL", (platform,)):
        if not (request.get('settings') or {}).get('auto_upload'):
            continue
        source = db.fetch('sources', request['source_id'])
        if source and not submissions.problem(source, settings, require_bound=False):
            return True
    return False


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
        elif platform == 'youtube' and config.discovery_enabled(settings) \
                and not settings.get('autopilot_review_before_publish', True) \
                and finished and settings.get('autopilot_auto_publish') \
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
        submitted_request = _submitted_upload_requested(settings, platform)
        dest = audience.destination(platform, settings)
        counts = {k: 0 for k in ('local_only', 'other_platform', 'preparing', 'checking', 'failed_check', 'ready',
                               'scheduled', 'review', 'planned_for_review', 'problems', 'preparation_stopped',
                               'waiting_time')}
        marks = ','.join('?' * len(ACTIVE_POSTS))
        posts = db.select("scheduled_publications", f"platform = ? AND status IN ({marks})",
                          (platform, *ACTIVE_POSTS))
        counts['scheduled'] = sum(p['status'] in ('approved', 'publishing') and p.get('planned_at') is not None
                                  for p in posts)
        counts['waiting_time'] = sum(p['status'] == 'approved' and p.get('planned_at') is None for p in posts)
        counts['review'] = sum(p['status'] == 'awaiting_approval' for p in posts)
        counts['planned_for_review'] = sum(p['status'] == 'awaiting_approval' and p.get('planned_at') is not None
                                          for p in posts)
        counts['problems'] = sum(p['status'] in ('reconciling', 'action_needed') for p in posts)
        occupied = {p['clip_id'] for p in posts}
        done = {p['clip_id'] for p in db.select('scheduled_publications',
                "platform = ? AND status = 'published'", (platform,))}
        for clip in clips:
            if clip['id'] in occupied or clip['id'] in done:
                continue
            project = db.get_project(clip['project_id']) or {}
            source = db.fetch('sources', project.get('source_id') or '') if project.get('source_id') else None
            from . import submissions

            targets = submissions.target_platforms(source or {}, settings)
            try:
                rights.gate(source, 'schedule', settings)
                allowed, _ = (rights.scheduling_allowed(source, platform, settings) if targets is not None else
                              rights.platform_allowed(source, platform, settings, stage='schedule'))
                allowed = allowed and (targets is None or platform in targets)
                if not allowed:
                    counts['other_platform'] += 1
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
            if not report or checked_text.get('metadata_id') != meta[0]['id'] or \
                    not gate.context_valid(report, clip, settings):
                counts['checking'] += 1
            elif report['status'] != 'passed' or checked_text.get('status') != 'passed':
                counts['failed_check'] += 1
            else:
                counts['ready'] += 1
        code, title, detail, link = _explanation(settings, platform, name, account, dest, permission[platform],
                                               counts, total, workers_alive, submitted_request)
        out.append({'platform': platform, 'code': code, 'title': title, 'detail': detail, 'link': link,
                    'counts': counts, 'automatic': bool(submitted_request or (permission[platform]['enabled'] and
                        not settings.get('autopilot_review_before_publish', True)))})
    return {'finished': total, 'checked': len(clips), 'sampled': total > LIMIT, 'platforms': out,
            'source_guidance': source_guidance(settings)}


def _explanation(settings: dict, platform: str, name: str, account: dict, dest: dict, consent: dict,
                 counts: dict, total: int, alive: bool, submitted_request: bool = False) -> tuple[str, str, str, str]:
    integrations, queue_link = "#/settings/integrations", "#/queue/review"
    if state.paused() or not settings.get("autopilot_enabled"):
        return ("paused", "Automatic work is paused",
                "Resume Autopilot to continue preparing and planning clips.", "#/missions")
    if account.get("needs_reconnect"):
        return ("account", f"{name} needs reconnection",
                "The saved sign-in needs to be renewed on this PC.", "#/settings")
    if not submitted_request and not settings.get(f"autopilot_{platform}"):
        return ("platform_off", f"{name} is not used by Autopilot",
                "Turn on this destination under How posts go out.", "#/missions")
    if dest["intent"] == audience.LOCAL_ONLY:
        return "local_only", f"{name} uploads are off", "Who watches is set to Keep clips on this PC.", integrations
    if not dest["confirmed"]:
        return "audience", f"Choose who watches on {name}", (
            "Finished clips stay on this PC until you choose and confirm their audience in Settings → Integrations."
        ), integrations
    if not submitted_request and not settings.get("autopilot_auto_schedule"):
        return "schedule_off", "Automatic scheduling is off", (
            "Finished clips are not assigned posting times. Turn on automatic scheduling in Settings → Advanced."
        ), "#/settings/advanced"
    if not alive:
        return ("workers", "Background work is not reporting",
                "Check Missions → Advanced → System on this PC.", "#/missions/system")
    review_first = bool(settings.get("autopilot_review_before_publish", True))
    if platform == "youtube" and not review_first and not submitted_request and not consent["enabled"]:
        message = consent.get("blocker") or (
            "Turn on automatic YouTube publishing, or approve each planned post yourself.")
        return "permission", "Automatic YouTube publishing is off for new clips", message, "#/missions"
    if settings.get("autopilot_publishing_paused"):
        return ("publishing_paused", "Publishing is paused",
                "Clips can still be made and scheduled; resume publishing on the Office.", "#/")
    if not submitted_request and not settings.get("autopilot_auto_publish"):
        return ("publish_off", "Scheduled uploads are off",
                "Turn on publishing approved posts in Settings → Advanced.", "#/settings/advanced")
    if counts["review"]:
        return "review", "Planned posts need your approval", (
            "Open Queue to check reuse permission, the exact clip, text and audience. "
            "Only posts you approve can upload at their posting time." if review_first else
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
    if settings.get("autopilot_active_start") == settings.get("autopilot_active_end"):
        return ("window", "Posting hours leave no time to upload",
                "Choose a posting window in Settings → Defaults.", "#/settings/defaults")
    if counts["ready"]:
        return "planning", "Finished clips are waiting for a posting time", (
            "The scheduler checks available posting hours, any chosen daily limit and platform waits. "
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
        if counts.get("other_platform") == counts["local_only"]:
            return "rights", f"Existing permission does not cover {name}", (
                f"These originals are covered only for another destination. Record a valid agreement that covers {name} "
                "or add your own originals. Changing upload limits does not change an agreement's terms."
            ), "#/missions/sources"
        return "rights", "Finished clips are for local use", (
            f"These videos have no recorded reuse permission for {name}. Add your original videos or record a valid "
            "creator agreement under Permissions & sources; being public does not grant permission. "
            "New automatic searches can focus on videos with verified reuse coverage."
        ), "#/missions/sources"
    if total:
        return ("waiting", "No new finished clip is ready to plan",
                "Recent clips are already planned, published or held. See Queue and Activity.", "#/queue")
    return ("rendering", "No finished automatic clips yet",
            "Autopilot needs usable video originals and strong moments before it can plan posts.", "#/missions/sources")
