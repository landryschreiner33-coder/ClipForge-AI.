"""The Crafting Apps inside ClipForge (docs/clipforge/CRAFT_APPS.md).

FilmCraft (video editor) and EffectCraft (motion graphics), free open-source apps from the ArtCraft team (MIT OR
Apache-2.0), run as part of ClipForge: ClipForge fetches their official release files itself (pinned by version and
SHA-256, into its own tools folder), the editor drives them headlessly through their command-line tools, FilmCraft
renders the final video, and FilmCraft's web editor opens inside the editor page.

* apps.py     which releases, where they live, downloading and checking them
* runner.py   calling the command-line tools (import, inspect, run steps, render)
* finish.py   the edit in FilmCraft: the cut, ClipForge's decisions as FilmCraft edits, the AI's edits, the render
* shots.py    effects shots made in EffectCraft and placed in the edit
* ai.py       the AI picking FilmCraft tools and EffectCraft shots (only with an AI service set up)
* web.py      FilmCraft's own editor inside the editor page (served by ClipForge, same origin)
"""
