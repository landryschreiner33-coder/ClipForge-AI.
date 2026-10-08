# Office screenshots

Taken on October 7, 2026 in the cloud test machine, at 1366×768 (Team: full page). All but `team.png` come from
the sandbox browser tests (`cd e2e && npm run test:sandbox`), which overwrite them on every run. The sandbox is a
throwaway copy of the app with fake YouTube and TikTok services and a made-up transcript instead of Whisper. That
machine has no NVIDIA GPU, so the GPU reading says *Error: No NVIDIA GPU was found* in every picture: that is the
honest reading there, not a fault of the screens.

| File | State | Where it comes from |
| --- | --- | --- |
| `first-run.png` | Empty, first start: Autopilot stopped, *Finish setting up*, the upload robots faded (no account) | `beginner-flow.spec.ts`, real app state |
| `working.png` | Active: Autopilot running, robots at their desks for the real jobs | `zero-touch-loop.spec.ts`, real jobs |
| `waiting.png` | A stream link waiting for its broadcast to start | `zero-touch-loop.spec.ts`, real jobs |
| `restarted.png` | The same, right after the workers were restarted | `zero-touch-loop.spec.ts`, real jobs |
| `paused.png` | Paused: nobody works, the bar offers Resume | `zero-touch-loop.spec.ts`, real state |
| `error-controlled.png` | CHECK in error, RADAR at 37%, SPLICE rendering | `robot-office.spec.ts`, **controlled answers** from the office API, so the top bar's *Autopilot: Off* (read from the real app) disagrees with the office's *Running* |
| `team.png` | The Team roster | `#/office/team` in the sandbox, captured once by hand (not rerun by the tests) |

The robots' contact sheet (all 25 in four directions, also captured by hand) is
[design/robots/contact-sheet.png](../../robots/contact-sheet.png).
