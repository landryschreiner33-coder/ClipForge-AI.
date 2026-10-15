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

Application revision: 0c2729d0a1e148e22da5bcdbd6db4ccb490dafa7
Included app.zip SHA-256: b7af499e03b140f374abcaa3b1c2cf3c9127719ee1f17fc336203a70acb10ccf
Setup verifies that hash and its known start.bat hash before installing or launching new app files.
The Python setup source is included for inspection. The archive is also inspectable with normal ZIP tools.

Bug-fix update:
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

Final application validation: 1,278 fast checks passed in 579.81 s; 43 final built-browser checks passed
in 93.25 s, with all 17 tested frontend hashes unchanged; production build passed in 10.32 s.
All 14 media/restart scenarios passed across full and targeted runs: the full attempt passed 12
with two repeat-discovery fixture timeouts in 1153.68 s; after a fixture-only compressed-clock
cache correction, the two private/public repeat scenarios passed in 374.57 s. This was not one
all-green full-media run. The final pure health-cadence refactor is covered by the full fast suite
and 77 focused checks; all 39 media-scope source hashes were unchanged. Detailed evidence is in
the application CLAUDE_HANDOFF.md and launcher/plain_setup_verification.json.
Source files: 498. Tested frontend files: 17.
Final delivery validation: 48 installer checks (1.576 s), 13 pin-helper checks (0.598 s), 12 builder checks (0.019 s)
and 10 exact-export helper checks (0.739 s) passed; the pinned archive was independently verified
against exact committed Git source and the final tested frontend manifest.
Owner Windows data, native Windows/RTX3050 operation, real account uploads, phone/Tailscale and a 24-hour
unattended soak remain unverified. This update preserves the earlier reviewed source setup and its profile
checks; it does not change GPU dependency pins or security settings.
