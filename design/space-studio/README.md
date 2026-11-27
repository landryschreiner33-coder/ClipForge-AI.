# The space studio (2026-11-19)

The owner asked on 2026-11-19 for ClipForge to become an animated space studio, with eleven reference pictures:

* seven screens: Studio, Brain · Memory, Brain · Styles, Projects, Publishing, Accounts and Settings · Appearance
* the enlarged ship cutaway
* three crew sheets: Command to Boost, Frame to CORE, and Switch to Dock

The references are kept with the project in `/mnt/project-files/space-studio/references/`. They are not in the
repository.

## What changed

| Screen | What it is now |
| --- | --- |
| Studio | **The ship and its crew.** A cutaway ship with 25 robots and CORE. Three engines with their own exhaust timing, the lounge, the bridge, the CORE chamber, the main corridor and the production rooms below. Room names are always shown, and each robot's state badge sits above its head. A name too long for one line in its room shortens to one word (Media, Story, Sound…); on a phone-sized ship every name does, and a resting robot's marker is a dot. A manager watching its team stands at its own desk, and on a smaller ship the badges shrink a little (from 21px towards 15px). Measured at 36 window sizes with every department at work: no badge covers another badge; no badge touches a room's name from 1330 wide up or from 768 to 1180 wide; at 1190 to 1320 and at 640 wide a badge can touch the bottom edge of the name of the room above it (at most 7% of its line), and on a phone (390 wide) up to a fifth. The badge always stays on top.<br>**The Studio panel** (right of the ship; under it on a narrow window), two tabs. **Working on**, the first: what is being made now on a screen with a light that says what it is doing (Making, Your turn, Paused, Waiting, Ready), its real step, progress only when measured and the robots on it; What's going on (the crew's last three real steps, and See everything); the queue; how many things need you; Talk to ClipForge AI; and at the bottom Next to publish, with a little upright screen of the clip, where and when it goes. **Make**: the four big choices and "Not sure what to make?" (Talk to ClipForge AI). The panel opens on Working on each visit (owner, 2026-11-19 8:47 PM).<br>**Under the ship.** Whole ship, Activity and Reduce motion.<br>**The bottom strip.** Real counts for today, and the computer's state. |
| Brain · Memory | **The graph.** The Brain's real knowledge graph sits over a spiral galaxy (`pages/galaxy.ts`, painted once from a fixed seed) with CORE at its centre. The galaxy holds still. **Lightning** (owner, 2026-11-19 8:49 PM): every real link is a jagged bolt of light in its collection's colour, every dot a glowing ball with a white-hot middle, and CORE a dark glass globe with filaments (`pages/brainLightning.ts`, a canvas under the dots). While motion is allowed each link strikes again every 2 to 5 frames at 12 frames a second, and the brightness varies only a little, so nothing flashes; it holds still under Reduced motion, Low power, a hidden or off-screen page or a lost connection. It is decoration: rings and the words "just used" still mark what a project used. A frame took about 3 ms with 160 notes here, and a computer that needs longer gets fewer frames. Beside the map (wider than 1180), the details are as tall as the map and scroll inside; a picked dot's name that would run off the map goes under the dot; on a narrow window the Brain's tabs wrap onto more lines. Branches are coloured: amber for Example videos, teal for Skills, ice blue for Recorded evidence.<br>**Picking a dot.** A light runs from CORE along the dot's real path, a ring settles around it, and its details open on the right with Open in editor.<br>**Search.** Search finds and focuses a real dot. |
| Brain · Styles | A form on the left and a caption preview you can play on the right (`components/StyleStudio.tsx`). The preview uses the fonts the renderer burns into clips. Words light up from the real playhead. |
| Projects | Big cards with real lengths, statuses, pins and menus, then a Live recordings table. |
| Publishing | Counts on the tabs and the time zone beside them. When nothing waits for review, an empty dock with DOCK's slowly turning amber beacon. On the right, the next scheduled post. |
| Accounts | The default YouTube channel in a hero card, beside a satellite drifting over Earth. A TikTok row with the action its real state needs. A line saying where sign-in tokens are kept. |
| Settings · Appearance | Choices apply at once and save to the account. The live Studio preview is the real app in an inert frame, at desktop, tablet and phone sizes. Its Motion control and the Studio's Reduce motion switch set the same browser choice. |
| Make clips | 1 Choose a video, 2 Pick what to make, 3 Make clips.<br>**Choices.** Highlights is "Pick the best moments". Full story is "Keep each story from start to finish". Story parts splits each story into Part 1, Part 2 and so on.<br>**More options.** Everything else waits under More options.<br>**When the clips are done.** A finished project says "Your clips are ready", and Review clips goes straight to the clips (`#/project/{id}/clips`). |

The type is Courier Prime (`frontend/src/assets/fonts`, OFL). The font notices ship with the app in
`frontend/public/third-party-fonts.txt` (built into `frontend/dist`, which the Mac app bundles; the font files' own
folder is not bundled). The sky is under every page and moves as if the ship were flying on to the right (Landry,
2026-11-20: "make the backround animated like we are moving"): the nebula picture `sky.jpg` holds still, far away; the
two star tiles, drawn at screen size, slide left slowly (the far one slower), moved by the browser's compositor; and a
canvas over them draws brighter stars that drift faster and twinkle, specks of dust rushing past and the odd shooting
star (`components/starSky.ts`, `components/StarSky.tsx`). The masthead paints its own copy of the sky to hide what
scrolls under it; its tiles are shifted to line up with the window's.

The black hole is painted in code (`components/blackHoleArt.ts`). It is large over Studio and a slim masthead on the
other pages. Its disk turns, the inner streaks faster: every streak is drawn again each frame on the graphics chip
(`components/blackHoleGl.ts`, WebGL), 30 times a second; without WebGL the canvas painter shows the same picture with
patches of light travelling round. If the frames come more than 45 ms apart through two 2.5-second stretches in a
row (a computer without a graphics chip), every black hole holds still for a while and then tries again: after 2
minutes, then 4, 8 and so on up to an hour each time it is still too slow. If the graphics chip loses the drawing (a
driver update or reset), the hole starts again on a fresh canvas; after three losses it keeps to the canvas painter.
Where the browser draws canvases on the graphics chip (Windows), a reset of the chip gives them back empty: the
canvas painter's hole, the sky's stars, the ship, the Brain's galaxy and lightning and the robot portraits are painted
again. The disk carries on from the picture last shown when it
starts moving again, and its clock counts only turning time. The chip is given the time since the start of the hour
(it counts in 32-bit numbers), and at each new hour every streak's starting point moves on by as far as it turned,
so the disk never jumps, however long the app is open.

Over Studio the big hole is normally seen from a ship orbiting it (`components/blackHoleOrbit.ts`, Settings →
Appearance → Space view: Orbit): every pixel's light is traced back from the camera and bent by the hole's gravity, so
the far side of the disk shows bent over the top of the shadow and under it, as in Interstellar. The camera sits 70
times the hole's radius away and 2-7.5° above the disk (2026-11-27): from closer (30) the near side of the disk loomed
over the lower half of the shadow like a brown bowl, and from higher the bent light over the top reached past the
hole's box and was cut off. The hole sits a little below the middle of its box, and its blue haze fades out well
inside the box, so the box never shows. Landry's little ship flies in front of it (`components/shipArt.ts`), banking
with the orbit, its flame flickering; the earlier grey dust squares in front of the hole are gone (the sky has its own
dust).

Pages and tabs arrive smoothly (`frontend/src/transitions.ts`): a new page fades in and rises 14 px, and a new tab
only what is under its tabs, 8 px (a second row of tabs that the change brings in fades in with it); the content is
there at once and only its look eases in. The Studio panel's tab highlight slides between Working on and Make.

## The art (`frontend/public/space/`)

| File | What it is |
| --- | --- |
| `ship.png`, `ship-lights.png` | The hull and rooms at native pixel size, cut from the ship cutaway with the drawn-in robots cleaned out (`tools/ship.py`, `tools/robots_bbox.py`), and the console and window lights that real work turns on. |
| `crew.png` + `src/space/sprites.json` | One atlas for the 25 robots, from the three crew sheets (`tools/cells.py`, `tools/extract.py`, `tools/crew.py`, `tools/frames.py`). Each robot has these frames: idle, blink, look left, look right, two walking steps, and four frames of its own work gesture. The gesture comes from its sheet: for example, Radar sweeps its reticle, Glyph highlights a caption line and Dock lights its beacon. |
| `core.png`, `consoles.png`, `exhaust.png` | CORE on its projector with orbiting rings; the console screens (asleep, awake, working); the three engines' flames. |
| `sky.jpg`, `stars-near.png`, `stars-far.png` | The nebula sky (`tools/sky.py`) and the crisp small stars (`tools/stars.py`). |
| `dock-scene.png`, `orbit.png`, `satellite.png` | Publishing's empty dock, and Accounts' Earth horizon and satellite (`tools/extract_scenes.py`). |
| `flyer-384.png`, `flyer-192.png` | Landry's little pixel-art ship (2026-11-27) that flies in front of the Studio's orbiting black hole (`components/shipArt.ts`), cut out of its picture and scaled down (`tools/flyer.py`; the picture itself is kept in the project files, `space-studio/flyer/`). |
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
  * the black hole's turning disk
  * the sky streaming past: sliding star tiles, twinkling stars, dust and shooting stars
  * the satellite's drift
  * the dock beacon on an empty review queue
  * the Brain map's lightning (it shows the real links, but its flicker shows no work)
* **Timing.** Pixel characters step at about 10 to 12 frames a second (`OfficeMap.tsx` draws every 83 ms). Distant
  scenery loops slowly. Ambient motions are staggered by a hash of each robot's id.
* **When it holds still.** The ship shows one still picture and draws every 250 ms when:
  * Reduced motion is on
  * the page is hidden
  * the feed is paused or lost
  * Low power is chosen

  Low power redraws once a second. When the ship is scrolled out of view, it is not drawn at all. When only the
  Brain is paused, CORE stops floating and its rings hold still while the rest of the ship carries on.

  The sky holds still under Reduced motion, Low power or a hidden page. The black hole also holds still while it is
  off screen, and for a while once the computer draws it too slowly. Under Reduced motion, pages and tabs arrive at
  once.

Decorative motion never touches processing. It reads the same snapshot the page already polls.

## Checks

* `tests/test_space_studio_lists.py`: the library rows behind the Projects cards and the Live recordings table.
* `e2e/tests`:
  * app-shell: Studio (its Make tab) and + Make offer the same four things; the panel's tabs work with the arrow keys;
    Talk to AI is in the navigation, the Brain's tabs and the Studio panel
  * posts: tab counts, the time zone pill and the next scheduled post
  * create: the three steps, More options and Review clips
* `e2e/sandbox`:
  * brain-graph: the lightning moves, and holds still with Reduced motion and in a hidden tab
  * brain-workspace: Talk to AI in the navigation opens the chat from any page
* The lightning's still check (`final/scripts/lightning.js` in the project folder): it changes with nothing set and
  with Calm, and holds still with the system's Reduce motion, Settings → Motion "Reduced", Low power and a hidden tab.
* Screenshots of every view at 1585×992, 1366×768 and 390×844, with the demo profile. The demo profile is
  `/mnt/project-files/ui-redesign/demo_app.py`, with stand-in posts and accounts routed in where the demo has none.

Not checked from the cloud: a real Windows or Mac machine, the owner's RTX 3050 laptop, real connected accounts, and
a real video going through the pipeline while the ship animates.
