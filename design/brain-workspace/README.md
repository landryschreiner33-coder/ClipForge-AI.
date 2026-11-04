# Brain graph previews

Captured from the built app on October 13, 2026, through `e2e/sandbox/brain-graph.spec.ts` in an isolated Chromium sandbox.
The graph and inspector use saved knowledge, real relationship types and recorded evidence fields. Positions and glow
are decoration, not hidden AI thoughts or a learning-progress measurement.

* [Desktop graph](graph-desktop.png): controlled fixture with 60 saved notes/preferences/example records, shared tags
  and recorded evidence supplied by intercepted test responses. These are illustrative test data, not owner records.
* [Mobile graph](graph-mobile.png): the same controlled fixture at 390px wide.
* [Empty graph](graph-empty.png): controlled empty memory state before adding the first note.

All five graph browser checks passed in the final production-build run, including exact-revision review, stale-edit
recovery, search, provenance, pan/zoom/keyboard controls, mobile layout, motion freeze and opening a saved item beyond
its disclosed graph cap. The complete regression run is recorded in `docs/IMPLEMENTATION_STATUS.md` after it finishes.
`build-sha256.json` records the distribution and screenshot hashes. Existing office previews retain their earlier
provenance; these captures do not claim Windows fonts/scaling, owner data or real account activity.
