# The space studio (2026-11-19)

The owner asked on 2026-11-19 for ClipForge to become an animated space studio, with eleven reference pictures:

* seven screens: Studio, Brain · Memory, Brain · Styles, Projects, Publishing, Accounts and Settings · Appearance
* the enlarged ship cutaway
* three crew sheets: Command to Boost, Frame to CORE, and Switch to Dock

The references are kept with the project in `/mnt/project-files/space-studio/references/`. They are not in the repository.

## What changed

| Screen | What it is now |
| --- | --- |
| Studio | **The ship and its crew.** A cutaway ship with 25 robots and CORE. Three engines with their own exhaust timing, the lounge, the bridge, the CORE chamber, the main corridor and the production rooms below. Room names are always shown, and each robot's state badge sits above its head.<br>**The right column.** Make something (four big choices), then Now making, the queue and the next scheduled post.<br>**Under the ship.** Whole ship, Activity and Reduce motion.<br>**The bottom strip.** Real counts for today, and the computer's state. |
| Brain · Memory | **The graph.** The Brain's real knowledge graph sits over a spiral galaxy (`pages/galaxy.ts`, painted once from a fixed seed) with CORE at its centre. Branches are coloured: amber for Example videos, teal for Skills, ice blue for Recorded evidence.<br>**Picking a dot.** A light runs from CORE along the dot's real path, a ring settles around it, and its details open on the right with Open in editor.<br>**Search.** Search finds and focuses a real dot. |
| Brain · Styles | A form on the left and a caption preview you can play on the right (`components/StyleStudio.tsx`). The preview uses the fonts the renderer burns into clips. Words light up from the real playhead. |
| Projects | Big cards with real lengths, statuses, pins and menus, then a Live recordings table. |
| Publishing | Counts on the tabs and the time zone beside them. When nothing waits for review, an empty dock with DOCK's slowly turning amber beacon. On the right, the next scheduled post. |
| Accounts | The default YouTube channel in a hero card, beside a satellite drifting over Earth. A TikTok row with the action its real state needs. A line saying where sign-in tokens are kept. |
| Settings · Appearance | Choices apply at once and save to the account. The live Studio preview is the real app in an inert frame, at desktop, tablet and phone sizes. Its Motion control and the Studio's Reduce motion switch set the same browser choice. |
| Make clips | 1 Choose a video, 2 Pick what to make, 3 Make clips.<br>**Choices.** Highlights is "Pick the best moments". Full story is "Keep each story from start to finish". Story parts splits each story into Part 1, Part 2 and so on.<br>**More options.** Everything else waits under More options.<br>**When the clips are done.** A finished project says "Your clips are ready", and Review clips goes straight to the clips (`#/project/{id}/clips`). |

The type is Courier Prime (`frontend/src/assets/fonts`, OFL). The sky is one fixed layer under every page: the nebula
picture `sky.jpg` and two star tiles at screen size.

The black hole is painted in code (`components/blackHoleArt.ts`). It is large over Studio and a slim masthead on the
other pages.

## The art (`frontend/public/space/`)

| File | What it is |
| --- | --- |
| `ship.png`, `ship-lights.png` | The hull and rooms at native pixel size, cut from the ship cutaway with the drawn-in robots cleaned out (`tools/ship.py`, `tools/robots_bbox.py`), and the console and window lights that real work turns on. |
| `crew.png` + `src/space/sprites.json` | One atlas for the 25 robots, from the three crew sheets (`tools/cells.py`, `tools/extract.py`, `tools/crew.py`, `tools/frames.py`). Each robot has these frames: idle, blink, look left, look right, two walking steps, and four frames of its own work gesture. The gesture comes from its sheet: for example, Radar sweeps its reticle, Glyph highlights a caption line and Dock lights its beacon. |
| `core.png`, `consoles.png`, `exhaust.png` | CORE on its projector with orbiting rings; the console screens (asleep, awake, working); the three engines' flames. |
| `sky.jpg`, `stars-near.png`, `stars-far.png` | The nebula sky (`tools/sky.py`) and the crisp small stars (`tools/stars.py`). |
| `dock-scene.png`, `orbit.png`, `satellite.png` | Publishing's empty dock, and Accounts' Earth horizon and satellite (`tools/extract_scenes.py`). |
| `src/space/ship-world.json` | The ship's floor plan: rooms, doors, halls, consoles and the lounge places (`office/world.ts`). |

`tools/build_space.py` writes these files from the cleaned art. `tools/preview.py` draws a still of the ship with
chosen robots working, to check positions without the app.

## How the ship is drawn

`office/StudioScene.ts` draws the ship with Canvas 2D, in layers. From back to front:

1. the hull
2. room lights
3. engine exhaust
4. CORE
5. consoles
6. the crew, sorted by depth
7. foreground desks

The HTML layer above the canvas has one button for each robot and each room. It also holds the room signs, the state
badges and the details panel. Keyboard, screen readers and touch use that layer. The canvas is never the only way to
reach something.

What moves and why (AGENTS.md rule 14):

* **Real work.** A robot turns to its console and its screen wakes only for a real job state from the office feed
  (`office/feed.py`). Handoffs between robots are the feed's real handoffs. When a clip newly arrives for review, DOCK's
  beacon cues once.
* **Decoration.** These show no work:
  * engine flames, on three different cycles
  * CORE's idle rings
  * blinking, looking around and lounge breaks
  * the galaxy turning
  * the black hole's travelling light
  * the satellite's drift
  * the dock beacon on an empty review queue
* **Timing.** Pixel characters step at about 10 to 12 frames a second (`OfficeMap.tsx` draws every 83 ms). Distant
  scenery loops slowly. Ambient motions are staggered by a hash of each robot's id.
* **When it holds still.** The ship shows one still picture and draws every 250 ms when:
  * Reduced motion is on
  * the page is hidden
  * the feed is paused or lost
  * Low power is chosen

  Low power redraws once a second. When the ship is scrolled out of view, it is not drawn at all.

Decorative motion never touches processing. It reads the same snapshot the page already polls.

## Checks

* `tests/test_space_studio_lists.py`: the library rows behind the Projects cards and the Live recordings table.
* `e2e/tests`:
  * app-shell: Studio and + Make offer the same four things
  * posts: tab counts, the time zone pill and the next scheduled post
  * create: the three steps, More options and Review clips
* Screenshots of every view at 1585×992, 1366×768 and 390×844, with the demo profile. The demo profile is
  `/mnt/project-files/ui-redesign/demo_app.py`, with stand-in posts and accounts routed in where the demo has none.

Not checked from the cloud: a real Windows or Mac machine, the owner's RTX 3050 laptop, real connected accounts, and
a real video going through the pipeline while the ship animates.
