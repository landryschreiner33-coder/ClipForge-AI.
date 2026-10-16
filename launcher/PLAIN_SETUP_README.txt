ClipFoundry source setup

1. Save any edits and close the previous ClipFoundry/setup windows.
2. Right-click ClipFoundry-Source-Setup.zip and choose Extract All.
3. Open the extracted folder and double-click Open-ClipFoundry.cmd.
4. Keep its console open. Setup prepares a short installation folder and opens the app in your browser.
   Use this same CMD file for later sessions.

Do not open the CMD from inside the ZIP. Keep Open-ClipFoundry.cmd, setup.py, app.zip and README.txt together
in the extracted folder. Leave the inner app.zip zipped; setup opens it for you.

This package includes the exact verified app archive, a readable Python setup.py and a plain CMD launcher.
It uses your installed Python. It includes no custom EXE launcher or PowerShell loader and does not change
antivirus settings, execution policy, Windows trust/certificates or the firewall, and grants no missing posting
permission.
Python packages/GPU libraries and the later speech-model download may still need internet access.
Python 3.11/3.12 and FFmpeg are recommended, as for normal ClipFoundry setup.

Do not turn off antivirus or restore/allow the blocked EXE to use this package. If Windows blocks this ZIP
or any extracted file too, stop and check Windows Security / Protection history for the exact threat name.
Source/integrity checks do not certify that antivirus accepts a file. Native Windows and Defender were not
available in the build environment.

Verified prior managed installations under the same Windows account keep their original data folder,
including Brain knowledge, accounts, settings and media. Unknown ordinary ZIP installations are not adopted.
Their data is left in place. No old files or virtual environments are copied over or deleted.
An active app/profile lock, multiple original profiles or unverifiable same-user managed revision stops setup.
Missing/malformed JSON markers are treated as unknown installations and left untouched.

Application revision: ab666fd5f2c4ca9c84a4fe9a2e874bc852437231
Included app.zip SHA-256: 1a251f7890fc260f1a89086dfac54b3b98cc87d517a04183fd5406d3400c9601
Setup verifies that hash and its known start.bat hash before installing or launching new app files.
The Python setup source is included for inspection. The archive is also inspectable with normal ZIP tools.

Search and Brain clarification update:
- Saved YouTube/Tavily keys are trimmed and checked for accidental extra text. Expired connected YouTube
  sessions refresh once using the same account. Invalid keys, disabled API projects, key restrictions and
  provider waits now have distinct, credential-safe explanations. Invalid or restricted keys still need
  correction at the provider; the app cannot create authorization or bypass quota.
- Save changes under Settings -> Integrations -> Search connections, then choose Test saved YouTube
  connection and Test saved Tavily connection. These explicit uncached checks do not import videos, run a
  web search or upload anything. YouTube uses a small quota-counted read, with one same-account retry if
  sign-in expired; Tavily checks account usage. Saving a key alone does not contact a provider.
- Missions shows each search provider separately. A working provider does not hide the other one's error.
  To use the connected YouTube account for search instead, remove the optional search key and save.
- Your reuse explanation stays with the exact reviewed post or selected posts. It is not Brain knowledge
  and does not teach future clips. Existing per-post review records remain; future clips still need review.
  Never share account keys or private app data in chat or a Claude handoff.

Earlier bug-fix update (included):
- New renders downmix the chosen audio track before processing, use clip-relative audio timing and limit peaks
  after gain. Preview a newly rendered clip before approval. Existing rendered/uploaded files are unchanged,
  and distortion already present in a source cannot be repaired by the limiter.
- YouTube made-for-kids answers require an actual Yes/No value. Made-for-kids and Private videos do not allow
  comments; other YouTube restrictions may also apply. Check YouTube Studio for affected existing posts.
  The app does not change a kids answer or audience merely to enable comments.
- Autopilot continues bounded discovery scans and lets available providers work while another provider waits.
  With spare preparation capacity and remaining source budget, scans run at most 15 minutes apart or at your
  faster configured interval. A busy queue retains the regular configured cadence. Quality, saved limits,
  budgets and API quotas apply.
- Settings -> Integrations -> Search connections accepts optional YouTube and Tavily keys. A connected
  YouTube account already supports search. Tavily's free plan currently includes 1,000 credits a month with
  no card; basic requests cost one credit. Choose Use free Tavily plan limits, then save, for 1,000 included
  credits and a $0 paid-search allowance. This is an app allowance, not a live provider balance; usage in other
  apps also counts at Tavily. Wikimedia Commons needs no key. Keys do not grant reuse or posting permission.
- Supported separate HLS video/audio tracks can be captured. Ended streams get bounded archive-recovery
  checks, although some never provide a usable recording. The specific Windows disconnected-socket cleanup
  error is handled without hiding unrelated errors. Native Windows remains unverified here.
- CLAUDE_HANDOFF.md is included in the application. Ask Claude to read it and AGENTS.md before continuing.
  Do not share account keys or your private app data in a handoff.

Autopilot prepares clips and assigns proposed posting times for review, even when reuse permission has not
been recorded yet. These times are local plans: nothing is sent to YouTube or a platform scheduler before
you approve it. Clips awaiting review stay on your PC even after their proposed posting time passes.

After updating:
1. Check Missions -> Prepare & schedule for review.
2. In Queue, watch clips directly from their cards. Check each source, valid reuse permission, caption,
   destination and proposed posting time.
3. Choose Quick approve for one YouTube post. To approve several, select the reviewed YouTube posts and
   choose Approve selected. You can select the visible YouTube posts, up to 50 at once.
4. In the dialog, check each post's audience and time. Choose a reuse-permission basis when requested.
   Presets avoid repeated typing; Other permission accepts a custom explanation. Use a basis that truthfully
   covers every selected clip, or approve separate groups when different clips need different explanations.
5. Answer the made-for-kids question if requested, confirm the review once, and approve. Successful posts
   are approved individually. Posts needing correction stay in review with an explanation.
6. Approved YouTube posts can publish at their scheduled times. Review past-due times before approving:
   those posts can upload on the next publishing check. Future clips each wait for your review.
   Individual Post review also offers presets and one combined confirmation. TikTok retains individual
   per-post review; manual handoff uses Approve for TikTok, with separate supported inbox/direct controls.

Standing automatic approval stops. Started/uncertain uploads retain their original identity for safe recovery;
already posted videos stay unchanged. Per-video audience settings, the made-for-kids answer, exact-file checks,
quality checks and platform/API limits still apply. No TikTok connection is needed for YouTube.
Earlier fixes remain: default app caps of 0 (unlimited), Brain guidance, phone dashboard and manager/boss
handoffs. Quiet rooms and Missions explain actual waits. Future owner caps persist.

An approval is bound to the exact selected post, file, text, source terms, account, audience and options;
it does not approve future clips. New arrivals are not selected automatically. Required credit, quality checks
and platform limits remain in place.

Enabled saved Brain guidance applies to new clips automatically. Topic matching follows source context and
spoken content through selection and supported rendering choices, including topic-tagged notes whose wording
does not appear in a generated clip title. Recognized guidance takes priority for its supported choices;
Settings fill the gaps and explicit clip-editor changes take priority. Examples provide measured duration
and their saved preferences or notes, not automatic visual-style learning. General reference text is
searchable; unsupported instructions do not become editing controls. Check a new clip's Brain influence to
see which saved items actually changed its plan or render. Previously rendered clips are not silently changed.

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
Owner Windows data, native Windows/RTX3050 operation, real account uploads, phone/Tailscale and a 24-hour
unattended soak remain unverified. This update preserves the earlier reviewed source setup and its profile
checks; it does not change GPU dependency pins or security settings.
