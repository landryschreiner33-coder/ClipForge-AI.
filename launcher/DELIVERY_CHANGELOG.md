# Delivery checkpoint: readable Windows source setup

## Search connection recovery and per-post reuse clarity — 2026-10-15 (America/Chicago)

App revision: ab666fd5f2c4ca9c84a4fe9a2e874bc852437231. Artifact base: 8fa4e5d.
The owner reported no clips and both search keys failing. Saved optional YouTube/Tavily keys are trimmed and
reject accidental headers, embedded whitespace and nontext values. Connected-account YouTube discovery
refreshes an expired sign-in once using the same account and counts both requests. API-key failure never
silently switches credentials. Credential-safe provider errors distinguish invalid/rejected/restricted keys,
disabled API projects, network/response problems and actual quota/Retry-After waits.

Search connections provides explicit uncached saved-connection tests. The YouTube test makes a small read
against the selected credential and can refresh the same connected account once; the Tavily test reads
account usage without a search. Saving alone calls no provider. Test requests respect existing allowances,
request serialization and service waits; no source import or upload occurs. Provider-specific Missions and
health status expose each failure independently, so another working provider cannot hide a bad connection.
The app cannot validate the owner's unavailable keys here or override provider restrictions.

Reuse explanations remain exact-post approval records, not Brain knowledge or future clipping guidance.
Shared single/bulk review controls and the saved post details now state that separation. Prior source rights,
required-credit, exact-file/account/audience approval and uncertain-upload recovery remain intact. Existing
Brain guidance, quality filtering, audio/live/Windows fixes and earlier selected-post review are included.

Final application validation: 1,373 fast checks passed in 755.18 s; all 14 real-FFmpeg/synthetic-media and
restart checks passed together in 945.34 s. All 51 final built-browser checks passed in 167.41 s, with all
17 tested frontend hashes unchanged. TypeScript and the production build passed (5.17 s). Focused checks also
passed: 77 provider, 88 diagnosis/health/phone, 113 independent search/Brain before the final wait-order fix,
then 53 wait/Brain checks. All 261 frozen source/frontend/Python-test hashes remained unchanged during final
verification. Eight screenshot-framing-only checks passed separately (28.60 s), with no product/assertion changes.
Tests used isolated data, synthetic media and fake platforms; no owner keys or real account upload was used.
All 504 archived source files match the exact Git revision except six intentional BAT CRLF exports;
all 17 browser-tested frontend files match. No extra/missing source files, EXE/DLL or runtime/credential paths
were included. The pinned archive was independently verified against committed Git and the tested frontend
manifest. Detailed application evidence remains in CLAUDE_HANDOFF.md and launcher/plain_setup_verification.json.
Final delivery validation: 48 installer checks (1.477 s), 13 pin-helper checks (0.511 s),
12 builder checks (0.012 s) and 10 exact-export helper checks (0.409 s) passed.
The builder checks all four outer ZIP members byte-for-byte and verifies both archive CRCs.
App archive: 41,944,927 bytes, SHA-256
1a251f7890fc260f1a89086dfac54b3b98cc87d517a04183fd5406d3400c9601.
Source setup ZIP: 41,886,576 bytes, SHA-256
b15943c878d15a91dd5837e8acc1c648588df87d6fbab498347ebe05d6ffe93a.

All nine prior exact managed-release pins remain, plus the current release (ten revisions total).
Python and historical PowerShell/BAT source pins/history agree. Verified same-SID original data profiles
remain intact. The builder and independent final inspection verified all four outer members and both CRCs.

No EXE was rebuilt or security setting changed. Historical EXE SHA-256 remains
3fb98871f38dc9d0dffa126a16cfe9223e8cb5b6f3b8aebe4ba493f940e0cf26.
Native Windows/Defender, owner data/RTX3050, real provider keys/uploads, phone/Tailscale and a 24-hour soak remain
unverified. Source/integrity checks do not certify antivirus acceptance. Verify the immutable remote ZIP before
sharing it. Extract All the outer ZIP and open its extracted CMD beside setup.py, app.zip and README.txt;
keep the inner app.zip zipped.

## Audio, comments, recurring discovery and live/Windows fixes — 2026-10-15 (America/Chicago)

App revision: 0c2729d0a1e148e22da5bcdbd6db4ccb490dafa7. Artifact base: 40393e4.
New renders downmix the selected first audio track before normalization and apply a compensated final peak
limiter after gain. Transcription selects the same audio track; clip-relative timing preserves delayed starts
and gaps as silence. Existing/source distortion and earlier renders/posts are not silently repaired or replaced.
YouTube kids answers are strict booleans, not truthiness of text such as "false". Current returned audience
flags take priority over historical requests. Review explains made-for-kids/Private/other comment restrictions;
no audience/kids answer is changed to force comments, and the upload API has no guaranteed comments-enable switch.

Discovery retains independent provider waits and recurs within 15 minutes when capacity and saved source
allowance permit; a busy queue retains the regular configured interval. Drained queues shorten stale regular
deadlines without polling postponement. Bounded provider pagination preserves ranks and YouTube time boundaries.
Status/phone reads stay read-only. Search connections exposes sealed optional YouTube/Tavily keys and official
setup help; Commons needs no key. The Tavily free preset sets 1,000 included monthly credits and a $0 paid-search
allowance, not a live provider balance. Quality, saved caps, API/cost limits and exact Retry-After remain.
Compatible separate HLS video/audio share a checked local relay/master and clock. Empty ended captures receive
bounded public-archive checks with durable recovery; absent/private/protected archives remain unavailable.
The specific native WinError10054 Proactor shutdown cleanup path closes/detaches correctly; unrelated errors
remain visible. The included CLAUDE_HANDOFF.md records exact changes, missing owner evidence and continuation steps.

Final app checks: 1,278 fast passed (579.81 s), 43 built-browser passed (93.25 s), production build (10.32 s),
all 17 tested frontend hashes unchanged. All 14 actual-media/restart scenarios passed across full and targeted
runs: the full attempt passed 12 with two repeat-discovery timeouts (1,274 deselected, 1153.68 s); after only the
compressed-clock fixture's discovery-list cache expiry correction, both private/public repeat scenarios passed
(374.57 s). This was not a single all-green full-media run. Production cache/quota behavior and all actual render,
report, upload-byte and restart assertions were unchanged by that fixture correction. All 39 media-scope source
hashes stayed unchanged; the later pure health-cadence refactor passed the final full fast run and 77 focused
health/phone/search checks. Rich full-attempt and targeted-run evidence remains separate in the verification JSON.
Focused checks also passed: 73 independent bugfix, 63 Windows/phone, 89 discovery, 61 queue/deadline/discovery,
47 final comments/search and 77 final health/phone/search. No real owner profile or platform upload was used.

All 498 archived source files match the exact Git revision except six intentional BAT CRLF exports; all 17
browser-tested frontend hashes match. Final delivery checks: 48 installer (1.576 s), 13 pin helper (0.598 s),
12 builder (0.019 s), 10 exact-export helper (0.739 s). An independent exact-export verification checked the
pinned archive against Git and the final browser manifest. The builder and final ZIP inspection verified all
four member hashes and both archive CRCs. All eight prior exact managed-release pins remain, plus the new one;
Python and historical PS/BAT source pins/history agree. Verified same-SID original data profiles remain intact.

App archive: 41,913,540 bytes, SHA-256
b7af499e03b140f374abcaa3b1c2cf3c9127719ee1f17fc336203a70acb10ccf.
Source setup ZIP: 41,855,919 bytes, SHA-256
6b48d845931595f7037d97ef36da68b773db3e5e1d8eab1748fccc4bbc6df882.

Extract All the outer ZIP and open its extracted CMD beside setup.py, app.zip and README.txt; keep inner app.zip
zipped. No EXE was rebuilt or security setting changed. Historical EXE SHA-256 remains
3fb98871f38dc9d0dffa126a16cfe9223e8cb5b6f3b8aebe4ba493f940e0cf26.
Native Windows/Defender, owner data/RTX3050, real provider keys/uploads, phone/Tailscale and a 24-hour soak remain
unverified. Source/integrity checks do not certify antivirus acceptance. Verify the immutable remote ZIP before
sharing it. Earlier Brain, selected-post approval, review-before-publishing and uncertain-upload guards remain.

## Faster selected-post approval and consistent Brain guidance — 2026-10-15 (America/Chicago)

App revision: 11bdb43523f9b01e82590d2dd9e67473d323c88d. Artifact base: 6cd12e1.
Queue provides inline video/full-text previews, Quick approve for one YouTube post and selection of up to 50
reviewed YouTube posts. One fixed batch preview shows account, audiences and times; reuse-basis presets avoid
repeated typing. A single combined confirmation approves each successful exact selected post individually.
Missing made-for-kids answers may be filled once; existing answers remain intact. Changed, blocked, replacement,
active or uncertain work is skipped with a reason. Identical-request retries keep their prior result. Future
arrivals are never selected or approved automatically. Single-post review shares the presets and combined
confirmation. TikTok retains its individual platform controls. Past-due timing is visible before approval.

Brain topic context now follows the source title and spoken words through candidate generation, including
cached/resumed and live paths, ranking, blueprint and render. Tagged example length is consulted after
transcription; per-candidate priorities avoid leaking unrelated transcript topics. Natural caption declarations
and named example feature fields are recognized. Bad-example observations no longer promote unwanted traits;
explicit corrective preferences remain usable. Settings fill unspecified choices, owner duration bounds remain
binding and explicit editor overrides win. The UI distinguishes recognized effects and measured example length
from searchable unsupported material. This does not add video-appearance recognition, external model calls,
raw-note transmission, silent rewriting of old media or publishing permission.

Final application checks passed: 1,195 fast (739.22 s), 11 actual-media/restart (1024.81 s), 31 built browser
(95.78 s), production build (9.44 s), plus 42 focused bulk, 19 independent approval audit and 86 Brain/context.
Actual-media cases include exact selected-post fake upload/restart and Brain-guided/owner-overridden caption
renders with persisted influence records. All 488 archived files match the exact Git revision except six
intentional BAT CRLF exports, and all 17 browser-tested frontend file hashes match. Final delivery checks:
48 installer (1.756 s), 13 pin helper (.737 s), 12 builder (.036 s), 10 exact-export helper (.778 s). The builder
verified each of the four outer ZIP members and both archive CRCs; the committed-source export was independently
verified against Git and the tested frontend manifest before packaging.

App archive: 41,865,645 bytes, SHA-256
7f34cc54d84ade2a920e49efd87e1f0ba37f14031c3300997efe7048b547d6f8.
Source setup ZIP: 41,808,314 bytes, SHA-256
4b365d80eee9d9a8deceb1a6a33ab35621d3f3d71818a7f2846bee62d50fe070.

The four-file readable setup preserves verified same-user managed profile history and the original data folder.
Instructions require Extract All and opening the extracted CMD beside setup.py, app.zip and README.txt; the
inner app.zip stays zipped. No EXE was rebuilt or security setting changed. Historical EXE SHA-256 remains
3fb98871f38dc9d0dffa126a16cfe9223e8cb5b6f3b8aebe4ba493f940e0cf26.
Native Windows/Defender, owner profile/RTX3050, real uploads, phone/Tailscale and a 24-hour soak remain unverified.
Source/integrity checks do not certify antivirus acceptance. Verify the immutable remote ZIP before sharing it.

## Local schedules and individual reuse review — 2026-10-14 (America/Chicago)

App revision: ec20aec76825a284393af00d812ec4a08a8beca3. Artifact base: f092834.
Autopilot defaults to preparing and scheduling for individual review. Accessible unblocked videos with
unrecorded reuse permission can reach local plans without becoming owned/licensed or approved to upload.
New posts wait for manual approval. Uncovered posts require an owner reuse statement and basis bound to the
exact post, source/current terms/credit, file/version, account, platform, audience, text and options.
Known required credit and physical-media checks remain binding; editing requires another review. Drafts do
not expire after 48 hours. Proposed times are local, not uploads to a platform scheduler. Approving a past-due
post permits prompt upload; its timing warning is displayed before approval.

Standing automatic approval is suspended. Old provably unstarted automatic approvals return to review while
preserving payload, audience, time and publication identity. Retry and not-published recovery cannot restore
an automatic grant. Started/uncertain uploads keep their session and account-bound readback. Existing posts,
saved media and earlier fixes remain. Verified same-SID managed installations retain their original profile;
unknown ordinary ZIP installations are left untouched. No EXE or security-setting changes were made.

Final app validation: 1,112 fast checks (529.54 s), nine actual-media/restart checks (879.93 s), 12 final built
browser checks (40.23 s), production build (8.79 s). All 478 archived files match the exact Git revision except
six declared BAT CRLF exports, and all 17 tested frontend hashes match. Independent delivery verification:
48 installer checks (1.313 s), 13 pin-helper (.387 s), 12 builder (.012 s), plus 10 exact-export helper checks.
The builder checks all four outer ZIP members byte-for-byte and their CRCs.

App archive: 41,816,502 bytes, SHA-256
8f873e6acd924db131fdd600e1b4a83b9a20895eedb4ab77bc1fd21e7726d2f2.
Source setup ZIP: 41,760,159 bytes, SHA-256
315098d40ca40fbb85f5c61c4b3cb5772f5bf32ddef9d4f1ee480706b8d1b0b0.

Native Windows/Defender, the owner profile/RTX3050, real account uploads, phone connectivity and a 24-hour
soak remain unverified. Source/integrity checks are not an antivirus certification. Immutable remote download
verification must match this ZIP, app payload, setup source and instructions before sharing its URL.

## Continuous eligible uploading and actual office activity

App revision: d0b7102e8273cee068531da554c8d83f3fa43f8f. Artifact base: 876d142.
Includes the earlier app changes plus unlimited app daily source/clip/platform defaults, all-day earliest
eligible slots, recorded one-time volume-only migration, verified uploadable source discovery and concrete
local-only guidance. Actual saved-guidance consultations and responsible manager/boss handoffs are visible.
Current terms and actual post credit are checked, with safe review and identity-preserving unstarted recovery.
Historical posts/Private visibility, missing consent, active/uncertain transfers, quality and platform/API/cost
limits remain protected. The app resumes eligible work when its saved Autopilot/permission are enabled.

Final app validation: 1,047 fast checks (556.14 s), eight real-media/restart checks (836.38 s), 11 final built
browser checks (94.42 s), production build (6.16 s), 93 focused reuse/publishing and 34 public/manual checks.
Controlled Brain screenshot and manager/boss GIF are included under design/robot-office/continuous.

Exact Git export verified all 472 committed app files, six intentional BAT CRLF transforms and 17 final tested
frontend hashes, with no local data/credentials/venv/PE additions. Pin helper now safely synchronizes readable
Python and historical PS/BAT source and retains every exact old managed release hash, including 718358f.
48 installer, 13 pin-helper and 12 package-builder checks passed; 10 disposable-Git export checks passed too.
Native Windows, Defender acceptance, actual owner profile/GPU/account uploads and 24-hour soak remain unverified.
The historical unsigned EXE is unchanged and still not recommended; no security settings were modified.

App archive: 41,784,343 bytes, SHA-256
32d0af142d7a34b6dcdd3d0b90048b0d977566bde4faf9b579c9ef496f468202.
Source setup ZIP: 41,728,594 bytes, SHA-256
ac3a11c159d389d44b11466e66efbd540cd67d64b749e4ff7ac9e86362783aba.

## Earlier first readable-source delivery

2026-10-13 (America/Chicago). Artifact branch: codex/clipfoundry-one-click. Base: 1f7db27.
Application payload stays at 718358f30110ab871e21059177f83ccd9ea3d3a9.

The owner reported Windows blocking ClipFoundry-Setup.exe as a virus. The detection name could not be found.
The historical wrapper is unsigned and launches embedded PowerShell; that might attract heuristics, but there
is no evidence establishing a false positive or the actual detection cause. No blocked EXE was restored,
allowed, renamed, rebuilt for evasion or recommended for use.

The recommended delivery is now ClipFoundry-Source-Setup.zip: a normal CMD file, readable standard-library
Python installer, unchanged pinned app.zip and README. It has no custom compiled launcher or PowerShell loader.
No app-archive network request is needed; Python dependencies/models still need their usual network access.
Windows Security, execution policy, trust/certificates, firewall and publishing permissions stay unchanged.

The Python port preserves same-Windows-SID v1/v2 managed profiles, known release/start hashes, short roots,
original data directories, mutex/byte-lock/process guards, verified archive paths, owned staging and an
exclusive no-replace move. Dependency setup completes before selecting the loopback port and opening the app.
Original Brain, settings, accounts, clips, code and virtual environments remain in place. Unknown ordinary ZIP
installs are not adopted or migrated. Missing/malformed markers remain unknown; unverifiable same-user managed
revisions or multiple original profiles stop setup. Existing managed checks identify marker/start bytes and
do not certify every previously installed file.

Independent review identified a dangling/nonregular lock entry that could be skipped by an is_file check.
The port now validates every matching lock path and refuses scan failures before app launch. Disposable tests
cover those regressions. Native Windows calls have explicit pointer/handle signatures, but their execution is
mocked here and remains a device check.

Actual checks run for this delivery:

* 48 readable-installer tests passed (root final run: 0.892 seconds). Disposable fresh/upgraded profiles,
  unchanged synthetic Brain/accounts/media/old venv, actual local byte lock and occupied ports, failed setup,
  cancellation of launch after a second lock check, ZIP traversal/symlinks and mocked Windows APIs are covered.
* 12 source-builder tests passed (root final run: 0.010 seconds). Exact member bytes, deterministic output,
  archive/start/pin tampering, prior-artifact preservation, Windows paths, case collisions, unwanted PE/runtime
  data, symlinks and ordinary CMD entry points are covered.
* Independent payload review: 507 ZIP entries / 462 source files exactly match the pinned Git revision except
  six declared BAT CRLF exports. All 17 tested frontend hashes match. No added/missing files, runtime data,
  venv, .env, special files, EXE/DLL or common credential signature matches were found. Signature matching is
  limited and is not an antivirus or comprehensive credential audit.
* Builder verified all four outer ZIP members byte-for-byte and their CRCs. Source ZIP: 37,740,282 bytes,
  SHA-256 d0ebd2fa3251fcde05daf28737f416729e384e725ac150aa9a65496ebfc3b21d.

The unchanged app previously passed 958 fast checks, eight real-FFmpeg/synthetic-speech media/restart checks,
seven controlled browser checks and a production build. Those are prior app checks, not repeated for this
delivery-only change. Historical Go/PowerShell files and their earlier tests are unchanged.

Not verified: native Windows installer/runtime/Defender acceptance, actual owner data, RTX3050, real social
accounts/uploads, phone/Tailscale connectivity and 24-hour unattended operation. Setup source and provenance
checks are not a malware scan or a promise that Windows will accept the download. If the ZIP or extracted
files are blocked, stop and inspect that detection instead of bypassing protection.

For continuation, use launcher/plain_setup.py and launcher/build_plain_zip.py rather than the historical
EXE wrapper. Review new app pins together with the retained release map, run the two Python suites, build
the ZIP, verify the exact app revision/tested frontend and publish a normal non-force artifact-branch commit.
The builder refuses unsynchronized pins. Do not change app dependency pins, publishing consent or original
data to solve delivery problems. Record final immutable download verification before sharing its URL.
