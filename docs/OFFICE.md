# The robot office: roles, events and the feed

The office shows what ClipFoundry's durable job queue is actually doing. The robots are **responsibilities**, not
separate programs or AI sessions, and they move only when a real job changes state.

## Hierarchy

| Department | Manager | Workers (job kinds they own) |
| --- | --- | --- |
| Boss Hub | COMMAND (Director) | (decides on failed tasks) |
| Discover | TRACKER | RADAR (`source_scout`, `feed_scan`, `live_watch`, `live_capture`), ARCHIVE (`identify_link`, `post_live`) |
| Analyze | VECTOR | PULSE (`trend_scan`), GAVEL (`rights_check`), BOOST |
| Clip Studio | FRAME | SPARK (`hunt_source`), STORY (`analyze_source`), SPLICE (`regenerate_clip`) |
| Captions | SCRIPT | GLYPH, QUILL (`package_clip`) |
| Schedule | CLOCK | (CLOCK owns `schedule_tick` itself) |
| Upload Dock | HARBOR | LOCK (audience verification), DOCK (`publish`) |
| System | SWITCH | CHECK (`quality_check`), PATCH (`maintenance`, `selftest`) |
| Brain Room | CURATOR | METRIC, SYNAPSE (`learn`) + CORE (the Brain itself, not a robot) |

- The mapping from job kind to role is `KIND_ROLE` in `clipfoundry/office.py`.
- A test checks that every job kind in `queue.WORKERS` has a responsible robot.
- Roles without their own job kind are BOOST, GLYPH, LOCK and METRIC. Their work happens inside a neighbour's job
  (scoring, captions inside rendering, the audience check inside publishing, statistics inside learning), so they
  stay idle rather than pretend.

## Reports and decisions

When a job ends, `autopilot/host.py` records three events in `autopilot_events`:

1. `office.worker_report`: role, job ID, stage, state, warnings, elapsed time, attempts.
2. `office.manager_review`: the department manager's review. `accepted` means it completed, `rework` means it will be
   retried, `on_hold` means it is waiting for a resource or a time, `escalated` means it failed for good, and
   `stopped` means it was canceled. Each review has a recommendation and a confidence.
3. `office.boss_decision` (on `escalated` only): COMMAND isolates the failure so other work continues. The failure is
   listed under Queue → Problems.

- Each record carries `rules: office-rules.v1`. They are deterministic rules over the job's recorded outcome, not an AI
  conversation.
- Frequent bookkeeping jobs (`schedule_tick`, `maintenance`, `feed_scan`) only create events when something goes
  wrong.
- Recording never fails or delays the job.

## Feed contract

| Endpoint | Purpose |
| --- | --- |
| `GET /api/office` | Authoritative snapshot: run state, mission, 25 robots with their real task, health, today, next upload, needs-you, audience, Brain, the last events, and `cursor` |
| `GET /api/office/events?after=<cursor>` | Events after the cursor, oldest first: `id` (unique, ordered), `at`, `type`, `role`, `job_id`, `department`, `ref_type`/`ref_id`, `data`. `gap: true` means more happened than fit, so the client reloads the snapshot instead of replaying a backlog |
| `POST /api/office/control` | `start`, `pause`, `resume`, `stop`, `pause_publishing`, `resume_publishing`. These are the existing durable controls, so repeated clicks reuse the current run |
| `GET /api/system/health` | Healthy / Degraded / Error / Unknown per check, with a reason and a next action |
| `GET /api/devlog` | The read-only development history (`.clipfoundry/ai-change-log.jsonl`, `AI_CHANGELOG.md`) |

The client deduplicates by `id` and shows when its data is stale. Animation never creates, approves or finishes
anything.

## Robot art

`frontend/src/robots/` holds the registry and the code-drawn pixel sprites: 25 roles plus CORE, 4 directions, 12
states. See [design/characters/README.md](../design/characters/README.md). The development gallery is at
`#/dev/characters`, and the read-only roster at `#/team`.
