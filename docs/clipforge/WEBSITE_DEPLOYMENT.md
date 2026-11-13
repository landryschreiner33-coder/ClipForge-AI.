# ClipForge website publication — November 4, 2026

Live: https://clipfoundry-studio.landryschreiner33.chatgpt.site

The owner requested reviewing and merging PR #16 and updating the existing public website. The website is a
preview/download page, not a deployed cloud studio. Its public audience and address are unchanged.

## Published source and artifact

- Site: `appgprj_6ae8b76d68108191bc36af565f138bed`
- Saved version: **3**, `appgprj_6ae8b76d68108191bc36af565f138bed~appgver_7e8440267980819186affbd5a1d0fd79`
- Website source commit: `626295c6e31b0120043483e21aceda2718d57a14`
- Deployment: `appgdep_6aeb6be63940819185f90f2769de8ce2`
- Native deployment result: **succeeded**, November 4, 2026, 17:31 UTC.
- Archive: `.openai/hosting.json` and `dist/` from that exact pushed commit; no source credentials or private data.
- Website checkout: `/workspace/sites/clipfoundry-downloads` (separate from the application repository).

## Changes

ClipForge branding, clearer hierarchy, both creation flows, Full stories within Make clips, real temporary-sandbox
screenshots, Brain guidance/styles/skills, multiple account connections and robot customization. Responsive preview
and installation tabs support keyboard navigation. Legal disclosure now explains the separately hosted source
version. The canonical robot icon and separate GitHub Pages/TikTok verification website are unchanged.

Availability is explicit: the new studio is a source preview; the existing downloadable desktop packages are older
ClipFoundry releases; there is no live cloud login, public signup or promised unlimited platform posting.
Full-video publishing and per-account scheduling are marked incomplete.

## Downloads preserved

- Mac: `macos-personal-2026-11-03-bc3ce2c/ClipFoundry-Mac-Apple-Silicon.dmg`, 191,813,213 bytes,
  SHA-256 `4fa4d423159c29d40f70632ae414c1fa047c7f72542e702f07f2e8ad0bb52d7d`.
- Windows: source setup at commit `fc7b1991e07dc9e58afc7fe74328a0874bf24e57`, 42,209,821 bytes,
  SHA-256 `267f1dc686d1584fa86d91c4f56bf4e8db7399ea1954bbe876f3698ded55bddc`.
- These downloads do **not** contain PR #16. A new native build/release is a separate remaining task.
- Mac remains an ad-hoc-signed personal preview, not Developer-ID-signed or Apple-notarized.

## Verification

Browser QA at 1440, 1024, 768, 390 and 320 pixels: no horizontal overflow, missing images, JS errors or failed local
requests. Keyboard preview/install tabs, FAQ, internal anchor targets, privacy/terms/version files and download
anchors with JavaScript disabled passed. Fresh app screenshots show the reviewed interface, without owner data.
Native Sites publication confirmed the live URL. Existing immutable downloads were retained, not rebuilt or
re-uploaded in this checkpoint. No real account sign-in, media upload or cloud processing service was tested.

## Rollback (only if needed)

Republish the previous saved version **2** with the same Site ID and audience:
`appgprj_6ae8b76d68108191bc36af565f138bed~appgver_67a4bdd134748191a76578d322b019f1`.
Previous source: `e8df8d718de6a6b42d9118e44375176874d6d85b`;
previous deployment: `appgdep_6aea47758b188191a727141520a951e8`.
Do not create another Site, replace its identity, remove the existing downloads or enable public studio signup.

## Shared download page on GitHub Pages — November 4, 2026 (Claude Code)

The owner asked for a website that both Claude and ChatGPT can update. It is the `download/` folder of the
`gh-pages` branch: https://landryschreiner33-coder.github.io/ClipForge-AI./download/ . Any assistant with push access
publishes it with a normal commit. `download/releases.json` holds the downloads, `download/build.py` writes and
checks the page, and `download/UPDATING.md` describes the procedure. The existing root pages of `gh-pages` are
unchanged. The Sites page above is a separate site; its workspace can link to the GitHub Pages download page.

### First publication of the shared download page — November 4, 2026

`gh-pages` commit `414ef86` added `download/`. It lists ClipForge 2026.11.04, both built from `06f459e`:
- Windows: https://github.com/landryschreiner33-coder/ClipForge-AI./raw/29c4a634a7fb8dae7686c24759b61b74a05620a6/ClipForge-Windows-Setup.zip
  (46,661,349 bytes, SHA-256 `c1738e2975b346368f75725cc8a73f26cd12dffd574b29b9cffc16f2daabdb19`).
- Mac: https://github.com/landryschreiner33-coder/ClipForge-AI./releases/download/clipforge-mac-2026-11-04-06f459e/ClipForge-Mac-Apple-Silicon.dmg
  (192,010,395 bytes, SHA-256 `1da040a23a88f73b9a800aeaa4f1d761808ba18363fc28c45241aaee5850b000`).

The previous ClipFoundry downloads are listed as older versions. To make the Sites page offer the same files, its
workspace replaces its two download links with these, or links to https://landryschreiner33-coder.github.io/ClipForge-AI./download/ .

## Studio upgrade release — November 5, 2026 (Claude Code)

Landry approved the release in the project thread ("release it"). Both downloads are built from source commit
`6ecdafc96ca99904c04ebae8ae9ff82a5cdb8884` (branch `claude/project-thread-x72wkd`, PR #20; not merged at the time
of release).

- **Mac:** https://github.com/landryschreiner33-coder/ClipForge-AI./releases/download/clipforge-mac-2026-11-05-6ecdafc/ClipForge-Mac-Apple-Silicon.dmg
  (192,306,837 bytes, SHA-256 `198706f383c54226375908133be527e568129e2855adc9fa4e02eca93b3e6c5d`). Unsigned personal preview (ad-hoc signature, not notarized),
  published unchanged from [build and test run 42050818316](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/42050818316)
  by [publish run 42060598566](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/42060598566).
- **Windows:** https://github.com/landryschreiner33-coder/ClipForge-AI./raw/69a930ec49561dbbb35d886f380160d752c4366b/ClipForge-Windows-Setup.zip
  (46,962,928 bytes, SHA-256 `89df9b2db92d0e276ca843d0026b4b81d14a50bb7b5c8b6d9f3e94c7abe5ea84`), built on
  `claude/clipforge-downloads`. New check: [Windows setup check run 42052332032](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/42052332032)
  installed the previous release with a synthetic setting on a GitHub Windows Server 2025 runner, then this ZIP over
  it; the data folder and setting were kept, the app served this commit's page and icon byte for byte, all 701 files
  matched, and it closed and reopened cleanly. FFmpeg was not installed there, so no video was processed on Windows.
- **Download page:** `gh-pages` commit `138c4f7` (previous: `414ef86`), merged from PR #21 at Landry's request and
  deployed by Pages run 42062766514. It is a squash of the checked commit `89c922b` with the identical tree; direct pushes
  to `gh-pages` were refused for this session, so it went through a review branch. Dark only, new sandbox screenshots
  (made-up media, throwaway data), the new features, the retired discovery removed from the copy and the robot roles,
  an FFmpeg step for Windows, a Questions section and a Support link. `build.py --check` and `--verify` passed; the
  page was checked at 1440, 390 and 320 px (no sideways scroll, no missing images or errors, keyboard, no JavaScript).
- **Sites page** (https://clipfoundry-studio.landryschreiner33.chatgpt.site): **unchanged**. This session has no
  access to its Sites workspace; it still links its older downloads. Its workspace can link to the GitHub Pages page.

`build.py --check` and `--verify` passed again on `138c4f7`. The github.io page itself could not be loaded from this
session. Rollback: revert `138c4f7` on `gh-pages` with a normal commit (never force-push); the 2026-11-04 files stay
listed under Older versions and their URLs never change. The previous Mac release and the Windows ZIP at `29c4a63`
are untouched.

## Smart editing and the Mac link fix — November 5, 2026 (Claude Code)

Landry asked in the project thread to merge both fixes and "update the website with the new fixed versions". Both
downloads are built from source commit `2e5238eb38e2e2f11f5c349b0ee8fee0b40a8d45` (PR #20's branch with PR #22, the
Mac YouTube link fix, and PR #23, smart editing and ClipForge AI). Listed as ClipForge 2026.11.05.2.

- **Mac:** https://github.com/landryschreiner33-coder/ClipForge-AI./releases/download/clipforge-mac-2026-11-05-2e5238e/ClipForge-Mac-Apple-Silicon.dmg
  (237,781,526 bytes, SHA-256 `14c78abe948634cc92a7c786aac0916534ef0f88cc52e7b5e9cc55af29c2169f`). Unsigned personal
  preview, published unchanged from [build and test run 42106643196](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/42106643196)
  by [publish run 42114038409](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/42114038409). It is
  about 45 MB larger than 2026.11.05 because it bundles Deno for YouTube.
- **Windows:** https://github.com/landryschreiner33-coder/ClipForge-AI./raw/d60445fb08b4f705448bddfef6e1a36e53fa7aa2/ClipForge-Windows-Setup.zip
  (47,042,861 bytes, SHA-256 `531e9ef012eb27705f7ed66b82325c9f2b048b854d4206c260541e9e0d63eb0d`).
  [Windows setup check run 42109581700](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/42109581700)
  installed the 2026.11.05 release with a synthetic setting, then this ZIP over it: same data folder and setting,
  this commit's page and icon, all 709 files, close and reopen. No FFmpeg on the runner, so no video was processed.
- **Download page:** `gh-pages` commit `65f026a` (previous `138c4f7`), pushed directly and deployed by Pages run 42114472648. New: Edit it for me, the
  optional free model for ClipForge AI (local Ollama/LM Studio or free Gemini, Groq, OpenRouter keys; Claude marked paid), the
  YouTube link fix, updated test counts (1,768 fast, 27 slow) and "not tested" lines for real AI models and keys and
  a real YouTube download. `build.py --check` and `--verify` passed (all eight files); checked at 1440, 390 and
  320 px (no sideways scroll, no errors). The github.io page itself cannot be loaded from this session.

Rollback: revert `65f026a` on `gh-pages` with a normal commit. The 2026.11.05 files stay under Older versions.

## ClipForge AI and FilmCraft inside the app — November 6, 2026 (Claude Code)

Landry chose "Merge and release" on the decision card for PR #28. Both downloads are built from source commit
`32485bd8c36b5f889bff565d15bd15828bc6aadf` (the release line `claude/project-thread-x72wkd` with PR #25, #26, #27 and
#28; the same tree as the tested head `ae2d5f5`). Listed as ClipForge 2026.11.06.

- **Mac:** https://github.com/landryschreiner33-coder/ClipForge-AI./releases/download/clipforge-mac-2026-11-06-32485bd/ClipForge-Mac-Apple-Silicon.dmg
  (237,930,523 bytes, SHA-256 `ff6358ca836ce8a9b39f98f07c495a09d2035749bf5a823235677d97b2e91fc1`). Unsigned personal preview, published unchanged from
  [build and test run 42311548798](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/42311548798)
  by [publish run 42316848534](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/42316848534).
- **Windows:** https://github.com/landryschreiner33-coder/ClipForge-AI./raw/9ddbd62ed93d775ea1bbb3d12060859530c07549/ClipForge-Windows-Setup.zip
  (47,304,093 bytes, SHA-256 `2abde3f1829a0cc36ab5eede866895f42a36316a7dc9148d96bf34bc0ef36888`).
  [Windows setup check run 42312199587](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/42312199587)
  installed the 2026.11.05.2 release with a synthetic setting, then this ZIP over it: same data folder and setting,
  this commit's page and icon, all 748 files, close and reopen. No FFmpeg on the runner, so no video was processed.
- **Download page:** `gh-pages` commit `eaa92df` (previous `b5afbd3`), pushed directly; Download page run
  42317711666 and Pages run 42317710696. New: ClipForge AI (the built-in model, its memory and chat, the twelve
  playbooks), Clean up the sound, FilmCraft and EffectCraft inside ClipForge, the editors' numbers and the BT.709
  colour fix, with the checked / not checked lists for this version. `build.py --check` and `--verify` passed. The
  github.io page itself cannot be loaded from this session.

Rollback: revert `eaa92df` on `gh-pages` with a normal commit. The 2026.11.05.2 files stay under All versions.

## ClipForge AI far smarter, long videos and the new look — November 7, 2026 (Claude Code)

Landry wrote "publish the new changes" after the smarter-AI report. PR #32 was merged into the release line as
`d1547e3`; its Mac build and test run ([42403806462](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/42403806462))
built and smoke-tested the app and passed the 1,969 fast tests but failed one slow render test (the fast-paced
"Edit it for me" got no punch-ins on an even synthetic voice), so the release waited for PR #33 (an even voice falls
back to the every-other-cut punch-ins). PR #33 was then merged into the release line as merge commit `95a70e0` (a direct fast-forward push of the
release line is not allowed from this session), and that merge commit's tree is identical to the tree of its head
`8593947e1e5bbabeec66c81527a858b71bc81102` (tree `679b1cb`), which both downloads are built from and name as their
source commit. `claude/project-thread-x72wkd` at `95a70e0` holds PR #31 long videos, PR #30 the new look, PR #32
ClipForge AI far smarter and PR #33. Listed as ClipForge 2026.11.07. The
record for 2026.11.06 is in PR #29, which is not merged yet.

- **Mac:** https://github.com/landryschreiner33-coder/ClipForge-AI./releases/download/clipforge-mac-2026-11-07-8593947/ClipForge-Mac-Apple-Silicon.dmg
  (248,199,864 bytes, SHA-256 `fd29c5c7a52964544ec5fd6de494b231c70a3f75bc87bcf3c4c4fc7bbfe267aa`). Unsigned personal preview, published unchanged from
  [build and test run 42407317796](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/42407317796)
  (native build and bundled-app smoke passed; 1,969 fast tests passed, 2 skipped; 27 slow tests passed, 1 skipped) by
  [publish run 42409176722](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/42409176722),
  dispatched on `claude/project-thread-hud5t5` at 8593947 (whose `.github/scripts/publish_personal_mac.py` carries the
  release-notes text).
- **Windows:** https://github.com/landryschreiner33-coder/ClipForge-AI./raw/055ede71072dfb4f6e97a578a0ea8042f6ef7bef/ClipForge-Windows-Setup.zip
  (49,199,526 bytes, SHA-256 `3cf76b9221c697fedaf90ad61e1c39ffe967634bddd48e4bbb2961bd813a2e24`).
  [Windows setup check run 42408340705](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/42408340705)
  installed the 2026.11.06 release with a synthetic setting on a Windows Server 2025 runner, then this ZIP over it:
  same data folder and setting, this commit's page and icon, all 788 files, close and reopen. No FFmpeg on the
  runner, so no video was processed. Record commit `7b3cd71` on `claude/clipforge-downloads`. (An earlier
  build from d1547e3, `raw/7ac285e`, passed check run 42404028631 but was never listed.)
- **Download page:** `gh-pages` commit `0a7f3f0` (previous `eaa92df`), pushed directly; Download page run
  42409903435 and Pages run 42409902826, both green. New: the meaning model, the scout and judge, the eyes, the ears, your taste, every Clip
  Score explained, Full stories without questions, big footage used where it is, your script, a smarter Edit it for
  me and the new look, with the checked / not checked lists for this version. `build.py --check` and `--verify`
  passed. The github.io page itself cannot be loaded from this session.

Rollback: revert `0a7f3f0` on `gh-pages` with a normal commit. The 2026.11.06 files stay under All versions.
