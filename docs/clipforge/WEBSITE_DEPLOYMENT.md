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
