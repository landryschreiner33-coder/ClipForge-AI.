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

## ClipForge AI as a real assistant, planned YouTube videos, animated shorts — November 13, 2026 (Claude Code)

Landry wrote "Release the new version with all the changes and update the website". The release line held PR #40
(story clips), #36 (animated shorts), #39 (local makers), #41, #38 (Make a YouTube video), #35, #42, #43 (deleting
projects and its clean-up) and #37 (ClipForge AI as a real assistant) at `492d254`. A fact-check of the release notes
found three app texts that still described old behaviour, so PR #44 fixed them and dated the privacy page; it was
merged into the release line as merge commit `1d455f6`, whose tree is identical to the tree of its head
`863e69ee9b69154ad189a1178d6940fd49b660a2`, which both downloads are built from and name as their source commit.
Listed as ClipForge 2026.11.13.

- **Mac:** https://github.com/landryschreiner33-coder/ClipForge-AI./releases/download/clipforge-mac-2026-11-13-863e69e/ClipForge-Mac-Apple-Silicon.dmg
  (253,930,009 bytes, SHA-256 `75fe4fc20feff91914ad72b6d03c550760409b6cdbb49c44e4f1d4ed18d851a3`). Unsigned personal
  preview, published unchanged from
  [build and test run 43410427464](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/43410427464)
  (native build and bundled-app smoke passed; 2,623 fast tests passed, 2 skipped; 30 slow tests passed, 1 skipped) by
  [publish run 43413905735](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/43413905735),
  dispatched on `claude/project-thread-e1uuap` at 863e69e (whose `.github/scripts/publish_personal_mac.py` carries the
  release-notes text).
- **Windows:** https://github.com/landryschreiner33-coder/ClipForge-AI./raw/74c4d43e3372138139013cfb7d0c0cd078831248/ClipForge-Windows-Setup.zip
  (50,107,742 bytes, SHA-256 `a70cffebbd07f2addc3fb9535e02837ce92a82893f27f77b7ed0e6e1efe859e1`).
  [Windows setup check run 43410898326](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/43410898326)
  installed the 2026.11.07 release with a synthetic setting on a Windows Server 2025 runner, then this ZIP over it:
  same data folder and setting, this commit's page and icon, all 865 files, close and reopen. No FFmpeg on the
  runner, so no video was processed. Record commit `8d5a242` on `claude/clipforge-downloads`. (An earlier build from
  492d254, `raw/240548b`, passed check run 43406275512 but was never listed; the 863e69e pins were rebuilt from the
  2026.11.07 launcher, so 492d254 is not in the launcher's release history.)
- **Download page:** `gh-pages` commit `e97c633` (previous `0a7f3f0`), pushed directly; Download page run
  [43416394802](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/43416394802) and Pages run
  [43416393149](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/43416393149), both green. Eleven
  changes with the checked / not checked lists for this version. By hand: "Three ways to make something" (Make clips
  with Highlights, Full story and Story parts; Make a YouTube video starting from your files and idea; Make an
  animated short), the headline and lead, and the AI question (the built-in model and the makers); four new
  screenshots (`studio.webp`, `make-clips.webp`, `make-video.webp`, `animated-short.webp`) taken at 1440×800 from the
  release build on an empty data folder (the short is the shorts check's sample, renamed "Octopus hearts");
  `editor.webp` is no longer used and was removed. `build.py --check` and `--verify` passed; the page was checked at
  1440, 1024 and 390 px (no sideways scroll, no console errors). The github.io page itself cannot be loaded from this
  session.
- **Legal pages:** `privacy.html` at the site root is now the app's `docs/legal/privacy.html` at 863e69e (effective
  November 13, 2026: ClipForge AI's chats, memories and helpers, deleting projects, uploads, animated shorts and the
  makers). `terms.html` and `index.html` were left as they were at first, because publishing them waited for
  Landry.
- **Legal pages, later the same day:** Landry chose to publish all three. A fact-check found the app's Terms
  (October 19) and legal home page still described automatic video searching, Windows-only installs and per-post
  approval as the default, and the privacy page still described discovery. PR #47 (merged as 5d862c8) corrected
  `docs/legal` against the code; the Terms are now effective November 13, 2026, the privacy page lists Find media's
  services (Openverse, Wikimedia Commons, Pexels), and the home page's download button and setup line point to the
  download page. `gh-pages` commit 5e369f8 publishes the three pages from fe0ac49 (site.css, icons and the TikTok
  verification file unchanged). Rollback: revert 5e369f8.

Rollback: revert `e97c633` on `gh-pages` with a normal commit. The 2026.11.07 files stay under All versions.

## Pictures and video on a rented cloud computer — ClipForge 2026.11.13.2, November 13, 2026 (Claude Code)

Landry wrote "Make sure the new version is released". The release line held, since 2026.11.13, PR #47 (legal pages
corrected), PR #48 (records) and PR #49 (pictures and video clips on a rented cloud computer) at `0716ba4`. PR #50
added the Mac release notes and was merged as `81f1718`, whose tree equals that of its head
`78c060152d2004f860fabf31b90dafab78c390ba`, which both downloads are built from and name as their source commit.
Listed as ClipForge 2026.11.13.2, dated November 13 (Landry's local date).

- **Mac:** https://github.com/landryschreiner33-coder/ClipForge-AI./releases/download/clipforge-mac-2026-11-13-2-78c0601/ClipForge-Mac-Apple-Silicon.dmg
  (255,750,672 bytes, SHA-256 `b8abf2287da8790f4127ed1a43d3d97bb0d666accfdfec4568b1d73ae8a65b56`). Unsigned personal
  preview, published unchanged from
  [build and test run 43550846491](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/43550846491)
  (native build and bundled-app smoke passed; 2,674 fast tests passed, 2 skipped; 30 slow tests passed, 1 skipped) by
  [publish run 43553368922](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/43553368922). Runs
  43546868998 and 43547488594 on the same commit stopped in the build step: GitHub's Mac runner could not connect to
  code.videolan.org while keeping dav1d's corresponding source. The third run, about 40 minutes later, passed.
- **Windows:** https://github.com/landryschreiner33-coder/ClipForge-AI./raw/dd6958beb6203c5a35d8300b168859d4c6334bf2/ClipForge-Windows-Setup.zip
  (50,159,553 bytes, SHA-256 `7832779d28dc67e2ce0557b63ebfa2ce2003a7556e8f2986a05dbfaac5e9f7dc`).
  [Windows setup check run 43547032569](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/43547032569)
  installed 2026.11.13 (863e69e, raw/74c4d43, now the check's previous release) with a synthetic setting on a Windows
  Server 2025 runner, then this ZIP over it: same data folder and setting, this commit's page and icon, all 868
  files, close and reopen. No FFmpeg on the runner, so no video was processed. Record commit `2a1ab84` on
  `claude/clipforge-downloads`.
- **Download page:** `gh-pages` commit `6e5918b` (previous `5e369f8`), pushed directly. Three changes (the cloud
  computer, its cost, the legal pages) with the checked / not checked lists. By hand: the AI question says pictures
  and clips can also be made on a rented cloud computer, which costs money while it is on. `build.py --check` and
  `--verify` passed; the page was checked at 1280 and 390 px (no sideways scroll).
- **Legal pages:** `privacy.html` and `terms.html` at the site root are the app's `docs/legal` copies at 78c0601: the
  published November 13 pages plus PR #49's text on the rented cloud computer (what it receives, what it keeps, that
  the company renting it charges by the hour). `index.html` is unchanged.

Rollback: revert `6e5918b` on `gh-pages` with a normal commit. The 2026.11.13 files stay under All versions.

## Clip live streams while they are live — ClipForge 2026.11.16, November 16, 2026 (Claude Code)

Landry wrote "Make sure you release the new changes". The release line held, since 2026.11.13.2, PR #52 (clip live
streams while they are live, several at once, with uploads during the stream) at `a187452`. PR #53 corrected the
texts a fact-check found and added the Mac release notes, and was merged as `9d0be40`, whose tree equals that of its
head `f3aea380648201cb39d3339fc39c45d021f9c84f`, which both downloads are built from and name as their source commit.
Listed as ClipForge 2026.11.16, dated November 16.

- **Mac:** https://github.com/landryschreiner33-coder/ClipForge-AI./releases/download/clipforge-mac-2026-11-16-f3aea38/ClipForge-Mac-Apple-Silicon.dmg
  (255,820,993 bytes, SHA-256 `815fe2d2755380d54bf5a8b5d7291ecee8cc07c41616c9b9b8aefd826e5b21b9`). Unsigned personal
  preview, published unchanged from
  [build and test run 43912561838](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/43912561838)
  (native build and bundled-app smoke passed; 2,721 fast tests passed, 2 skipped; 31 slow tests passed, 1
  skipped) by [publish run 43921441880](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/43921441880).
  The native job's first four tries (run 43897847676 twice, run 43909484088, run 43912561838's first attempt) were
  cancelled before starting because GitHub had no Apple-silicon Mac runner free.
- **Windows:** https://github.com/landryschreiner33-coder/ClipForge-AI./raw/26ef3a156b7b3a6fc6f122aa101cc15ad68fcb92/ClipForge-Windows-Setup.zip
  (50,216,384 bytes, SHA-256 `e7a32c7c54551e37258f434da46dcf64e205d5760a15c0a8398f4e5d2bef09f9`).
  [Windows setup check run 43898294309](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/43898294309)
  installed 2026.11.13.2 (78c0601, raw/dd6958b, now the check's previous release) with a synthetic setting on a
  Windows Server 2025 runner, then this ZIP over it: same data folder and setting, this commit's page and icon, all
  872 files, close and reopen. No FFmpeg on the runner, so no video was processed. Record commit `622dfef` on
  `claude/clipforge-downloads`.
- **Download page:** `gh-pages` commit `c68f266` (previous `6e5918b`), pushed directly. Seven changes (live streams,
  the recording limits, uploads during the stream, several streams, Stop recording, the Cancel/Stop all fix, the legal
  pages) with the checked / not checked lists. By hand: Make clips no longer says live links work like a file (the
  app refuses them there) and points to Clip a live stream; "Nothing posts by surprise" and "Will it post without
  asking?" name Make & upload clips; "Does ClipForge find videos for me?" names live streams. `build.py --check` and
  `--verify` passed here and in Download page run 43927842607; Pages run 43927842275.
- **Legal pages:** `index.html`, `privacy.html` and `terms.html` at the site root are the app's `docs/legal` copies at
  f3aea38, effective November 16: live streams on the legal home page, in the privacy page (what is recorded and kept,
  when the app contacts the stream's site, a channel link checked until it goes live) and in the Terms (a live
  recording kept on cancel, deleted with its project).

Rollback: revert `c68f266` on `gh-pages` with a normal commit. The 2026.11.13.2 files stay under All versions.

## The cloud computer gets its own section in Settings — ClipForge 2026.11.16.2, November 16, 2026 (Claude Code)

Landry could not find where to connect a cloud computer and asked that it be merged and released. It was (PR #49 in
2026.11.13.2 and 2026.11.16), but only as one button in the ComfyUI box on Settings → Pictures, video, voice. PR #55
gives it its own section, **Settings → Cloud computer**, and was merged as `77eaa99`, whose tree equals that of its
head `fa5e1396eaec78387b5ab22432926e9fed4e0773`, which both downloads are built from and name as their source commit.
Listed as ClipForge 2026.11.16.2, dated November 16 (Landry's evening; 2026-11-17 UTC).

- **Mac:** https://github.com/landryschreiner33-coder/ClipForge-AI./releases/download/clipforge-mac-2026-11-16-2-fa5e139/ClipForge-Mac-Apple-Silicon.dmg
  (255,828,420 bytes, SHA-256 `d8b6ba86d1d38d75e30e3c7f9f922470dfbf82f2156f836e513d56ec80c6d530`). Unsigned personal
  preview, published unchanged from
  [build and test run 44018676801](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/44018676801)
  (native build and bundled-app smoke passed; 2,721 fast tests passed, 2 skipped; 31 slow tests passed, 1 skipped) by
  [publish run 44022165510](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/44022165510).
- **Windows:** https://github.com/landryschreiner33-coder/ClipForge-AI./raw/eceeeb15fe63eb892cfe375adfda532e135925f4/ClipForge-Windows-Setup.zip
  (50,221,270 bytes, SHA-256 `e6f0c8014cb44f38fe98e5807dea5674c875ab4a339e164dc28bd31a32aea859`).
  [Windows setup check run 44020274850](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/44020274850)
  installed 2026.11.16 (f3aea38, raw/26ef3a1, now the check's previous release) with a synthetic setting on a Windows
  Server 2025 runner, then this ZIP over it: same data folder and setting, this commit's page and icon, all 872 files,
  close and reopen. No FFmpeg on the runner, so no video was processed. Record commit `649817e` on
  `claude/clipforge-downloads`.
- **Download page:** `gh-pages` commit `3166005` (previous `c68f266`), pushed directly. One change with the checked /
  not checked lists; "Do I need an AI subscription?" now names Settings › Cloud computer. `build.py --check` and
  `--verify` passed here and in Download page run 44023075391; Pages run 44023075193.
- **Legal pages:** unchanged. The privacy page's "A cloud computer in Settings → Pictures, video, voice" is still where
  that choice is (it is now on both pages).

Rollback: revert `3166005` on `gh-pages` with a normal commit. The 2026.11.16 files stay under All versions.

## Live clips, channels and a smarter ClipForge AI — ClipForge 2026.11.19, November 19, 2026 (Claude Code)

Landry wrote "Make sure all the new changes are merged and then release them". The release line
`claude/project-thread-x72wkd` held the three finished pull requests since 2026.11.16.2: #58 (choose which channels
each post goes to), #57 (live clip quality, split view, take turns between channels, Stop clipping) and #59 (smarter
chat, Brain-led clip picking, longer clips, lessons from results, post text rules). PR #60 corrected the Mac notes and
the legal pages after a fact-check and was merged as `5430f7c`, whose tree equals that of its head
`13e1fcbb430dabfcee461fc191c04376c841dc58`, which both downloads are built from and name as their source commit.

- **Mac:** https://github.com/landryschreiner33-coder/ClipForge-AI./releases/download/clipforge-mac-2026-11-19-13e1fcb/ClipForge-Mac-Apple-Silicon.dmg
  (232,165,236 bytes, SHA-256 `d1acc5df77d74d31708ef361f2f77583f56591be500008cce3cf4ead798a0a2b`). Unsigned personal preview, published unchanged from
  [build and test run 44599070088](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/44599070088)
  (native build and bundled-app smoke passed; 3,105 fast tests passed, 2 skipped; 31 slow tests passed, 1 skipped) by
  [publish run 44604316140](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/44604316140)
  (attempt 1 was cancelled after 15 minutes with no macOS runner; attempt 2 re-ran it).
- **Windows:** https://github.com/landryschreiner33-coder/ClipForge-AI./raw/7122cce8084adcafb20554905c960a2ecca90ba8/ClipForge-Windows-Setup.zip
  (50,448,541 bytes, SHA-256 `a46cd22df7f435baf311e26d40ef261c1968d08795a2d1fdedfa819036f4b333`).
  [Windows setup check run 44599233122](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/44599233122)
  installed 2026.11.16.2 (fa5e139, raw/eceeeb1, now the check's previous release) with a synthetic setting on a Windows
  Server 2025 runner, then this ZIP over it: same data folder and setting, this commit's page and icon, all 889 files,
  close and reopen. No FFmpeg on the runner, so no video was processed. Record commit `036771e` on
  `claude/clipforge-downloads`. A first build from `150978b` (before the legal fixes, raw/1286dca, check 44596262908
  passed) is not listed.
- **Why the DMG is smaller:** 232.2 MB against 255.8 MB for 2026.11.16.2. Nothing in the packaging changed; the
  build installed opencv-python 5.1.0.95 (a macOS 15 wheel, 25.8 MB) instead of 5.0.0.93 (48.3 MB), since
  `requirements.txt` asks for `opencv-python>=4.8`. The bundled app imported it in the native smoke check.
- **Download page:** `gh-pages` commit `8809e3e` (previous `3166005`), pushed directly. Ten changes with the checked /
  not checked lists; the "several accounts" line now says you tick which accounts each post, video or live stream
  goes to. `build.py --check` and `--verify` passed here and in Download page run 44608126498; Pages run 44608125226.
- **Legal pages:** the root `privacy.html` and `terms.html` are copies of `docs/legal` at 13e1fcb, effective
  November 19, 2026. A fact-check of the release texts against the code (three checkers by area, a skeptic for each
  checker's findings) confirmed 18 errors, all corrected before release. The privacy page now says Disconnect deletes
  only the sign-in tokens (the account's ID, name, picture link and settings stay until the data folder is deleted;
  the page's older Disconnect item said otherwise too), and covers split view's saved face cam position, the
  channel share choice saved with a Make & upload request, the memory and skill words kept with a clip, the Brain
  words sent to a model and a live recording's last minute sounds. The Terms say a Make & upload request names the
  ticked YouTube channels and how clips are shared.

Rollback: revert `8809e3e` on `gh-pages` with a normal commit. The 2026.11.16.2 files stay under All versions.

## The space studio — ClipForge 2026.11.19.2, November 19, 2026 (Claude Code)

Landry wrote "once done release the changes" (November 19, 9:56 PM Chicago time). The release line
`claude/project-thread-x72wkd` held PR #62 (the space studio, merged as `8c08f73`). PR #63 added the Mac release notes,
corrected after a fact-check, and was merged as `54ec586`, whose tree equals that of its head
`0597fefa2a026a5c5244114b74fbe0e28d4262b9`, which both downloads are built from and name as their source commit.

- **Mac:** https://github.com/landryschreiner33-coder/ClipForge-AI./releases/download/clipforge-mac-2026-11-19-2-0597fef/ClipForge-Mac-Apple-Silicon.dmg
  (232,004,809 bytes, SHA-256 `b4d8cec8ed054a52d98c82aff748af967dcb8271f862c21645d42e6d2883db86`). Unsigned personal
  preview, published unchanged from [build and test run 44677488448](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/44677488448)
  (native build and bundled-app smoke passed; 3,109 fast tests passed, 2 skipped; 31 slow tests passed, 1 skipped) by
  [publish run 44681038739](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/44681038739).
- **Windows:** https://github.com/landryschreiner33-coder/ClipForge-AI./raw/70f345049e1a4486f54fd0aaa50f42a08a11d7f1/ClipForge-Windows-Setup.zip
  (50,449,556 bytes, SHA-256 `e1116e65ed4c162d7b90a43e662fe79d6901b977698548b359f3d3b9c960e878`).
  [Windows setup check run 44677612640](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/44677612640)
  installed 2026.11.19 (13e1fcb, raw/7122cce, now the check's previous release) with a synthetic setting on a Windows
  Server 2025 runner, then this ZIP over it: same data folder and setting, this commit's page and icon, all 948 files,
  close and reopen. No FFmpeg on the runner, so no video was processed. Record commit `95aac79` on
  `claude/clipforge-downloads`. The first builds from `36efa8b` (the Mac notes before the fact-check; Mac run
  44673939916 and Windows check 44674145380 passed, raw/7937c41) are not listed.
- **Download page:** `gh-pages` commit `e349d2d` (previous `8809e3e`), pushed directly. Eight changes with the checked /
  not checked lists; new pictures of the Studio, the ship, Make clips, Make a YouTube video, the animated short maker
  and the Brain from a throwaway sandbox with made-up media; new portraits of the 25 robots; the crew text names the
  ship's rooms. `build.py --check` and `--verify` passed here and in Download page run 44681723162; Pages run
  44681722366.
- **Fact-check:** the Mac notes, the download page text and the pictures' descriptions were checked claim by claim
  against the code by four checkers (studio, clips, Brain, look) with a skeptic for each checker's findings: 19
  confirmed errors, all corrected before release (the Mac notes in `0597fef`, the rest on `gh-pages`); the corrected
  sentences were checked again (two checkers, a skeptic each), and three more download page wordings were corrected
  (What's going on, the screen's light, larger text). The privacy page and Terms are unchanged: nothing stored, sent or
  deleted changed.

Rollback: revert `e349d2d` on `gh-pages` with a normal commit. The 2026.11.19 files stay under All versions.
