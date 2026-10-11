# PR #14 visual evidence

Captured on 2026-10-08 on Linux/Chromium with isolated test data, no owner accounts and no NVIDIA GPU. The displayed
GPU error is the actual health reading here. Desktop images are 1440×900 unless noted; browser workflow images
include 1366×768. No image proves real-account posting, CUDA execution or Windows scaling.

| File | What it demonstrates | Provenance |
| --- | --- | --- |
| [office-all-25.png](office-all-25.png) | All 25 readable, named robot stations and overhead states | Throwaway app, stopped real state |
| [office-details.png](office-details.png) | Selected robot’s role, identity and task details | Same app, actual paused/empty task |
| [team.png](team.png) | Complete cast and individual identities | Actual Team registry |
| [handoff-controlled.png](handoff-controlled.png) | Dependencies, blocked/error/waiting states and next robot | Controlled office API responses, not actual processing |
| [office-motion-controlled.mp4](office-motion-controlled.mp4) | Working animation, report handoff, decision reaction, then Reduced | Controlled event responses; system reduced motion is emulated and explicitly overridden with Full |
| [brain-knowledge.png](brain-knowledge.png) | A document saved, approved and reloaded | Brain sandbox browser test, actual upload/storage |
| [brain-influence-preview.png](brain-influence-preview.png) | Same preference lookup in Try a decision | Preview only; no clip/result created |
| [brain-later-decision.png](brain-later-decision.png) | Uploaded guide changes a later persisted blueprint: bold → minimal | Actual upload, approval, blueprint build, validation and SQLite save; synthetic transcript, no render/publish |
| [brain-influence-proof.json](brain-influence-proof.json) | Stored revision and before/after values behind that screenshot | Actual saved influence record; no invented performance data |
| [brain-example.png](brain-example.png), [brain-example-mobile.png](brain-example-mobile.png) | Good/bad example controls, labels, measured media and responsive form | Actual upload of a small synthetic bad-example MP4, desktop and 390 px mobile |
| [working.png](working.png), [waiting.png](waiting.png), [restarted.png](restarted.png), [paused.png](paused.png) | Office follows real local jobs, upcoming-stream wait, restart and deliberate pause | Complete-loop sandbox: real handlers and FFmpeg, fake platform/transcript fixtures |
| [first-run.png](first-run.png) | Setup on a fresh installation | Beginner sandbox, real app state |
| [error-controlled.png](error-controlled.png) | Error icon and readable state layout | Controlled office responses; top app state is separately read |

The [real-job recording excerpt](office-real-jobs.mp4) shows seconds 8–22 of the passing complete-loop browser recording: actual office jobs/events and animation, with fake platform discovery/account APIs and synthetic transcript inputs. It is not a real-account or GPU recording.

[processing-timings.json](processing-timings.json) records actual active stage transitions from that run; [PERFORMANCE.md](../../../docs/PERFORMANCE.md) explains its limits. The robot contact
sheet is [design/robots/contact-sheet.png](../../robots/contact-sheet.png). These assets are evidence, not runtime
activity data shipped into the app.
