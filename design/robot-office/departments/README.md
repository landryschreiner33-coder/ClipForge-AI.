# Department attendance and Brain visual evidence

These captures show the production frontend against the disposable local sandbox at http://127.0.0.1:8844.
Captured 2026-10-09T14:19:13.572Z; source base `e896632ac69813a48ad85d67b1132a75a11cf303` with the current department/source edits built
into `frontend/dist`. Those edits were uncommitted at capture time; the commit containing this evidence also
contains the captured implementation. SHA-256 for all 14 production build files,
fixture rows, layout bounds, console checks and transfer timings are recorded in [evidence.json](evidence.json).

The work screenshots and video visibly say **ANIMATION PREVIEW · CONTROLLED TEST STATES**. Playwright fulfills
only the browser's Office snapshot/events responses: STORY and SPLICE initially have separate running jobs,
SYNAPSE has a controlled Brain evaluation, and FRAME/CURATOR use the backend's Working-without-own-task manager
pattern. Idle peers attend their active departments without receiving fake jobs or progress. Health readings
are the unmodified sandbox readings.

A fresh controlled `job_stage` event moves the same `preview-render` job from SPLICE's render step to GLYPH's
caption step. The production controller performs approach, one-document pass and receipt. STORY stays Working,
so SPLICE returns to its own Studio desk as support. Observed timings: approach: 9.15 s; pass: 17.84 s; received: 19.05 s; splice-returned-studio: 27.94 s. No job is created, started,
published or uploaded. Non-read API requests are blocked by the capture harness; zero writes were attempted.

| File | Evidence |
| --- | --- |
| [office-desktop-controlled.png](office-desktop-controlled.png) | 1440×900 whole office with all 25 identities and current fixture states. |
| [studio-department-controlled.png](studio-department-controlled.png) | Complete Studio: FRAME oversees, SPARK supports, STORY and SPLICE work. |
| [handoff-controlled.png](handoff-controlled.png) | The genuine controller pass phase for the controlled SPLICE → GLYPH event. |
| [studio-return-controlled.png](studio-return-controlled.png) | SPLICE back at its Studio desk while STORY remains Working. |
| [brain-department-controlled.png](brain-department-controlled.png) | Processing Brain core with SYNAPSE working, METRIC supporting and CURATOR overseeing. |
| [office-laptop-controlled.png](office-laptop-controlled.png) | 1280×720 whole office; world width 696.0 px and controls end at y=717.0. |
| [office-mobile-list-controlled.png](office-mobile-list-controlled.png) | 390×844 List viewport, saved as a full-page image. |
| [office-mobile-studio-controlled.png](office-mobile-studio-controlled.png) | The same 390 px viewport using the Studio camera, saved full-page. |
| [department-work-controlled.mp4](department-work-controlled.mp4) | 37.40 s, 1440×900 H.264: Studio, handoff, Studio return, active Brain, whole office. |
| [lounge-idle-actual.png](lounge-idle-actual.png) | Separate actual stopped-sandbox snapshot, labeled **OFF-DUTY ANIMATION · ACTUAL STOPPED SANDBOX**; no role/event injection. |

All Map captures use the Pixi renderer. The laptop controls are within the viewport; both mobile views have
no horizontal document overflow (office-mobile-list-controlled.png: true; office-mobile-studio-controlled.png: true). The capture run
reported 0 page errors and 0 console errors. Chromium ran
headless on Linux. The recording is an animation preview, not a processing-speed, Windows or RTX 3050 benchmark.
Earlier lounge evidence is unchanged in [../lounge](../lounge/README.md).
