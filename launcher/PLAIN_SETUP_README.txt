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

Application revision: 11bdb43523f9b01e82590d2dd9e67473d323c88d
Included app.zip SHA-256: 7f34cc54d84ade2a920e49efd87e1f0ba37f14031c3300997efe7048b547d6f8
Setup verifies that hash and its known start.bat hash before installing or launching new app files.
The Python setup source is included for inspection. The archive is also inspectable with normal ZIP tools.

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

This revision passed 1,195 fast checks (739.22 seconds), 11 actual-media/restart checks (1024.81 seconds),
31 built browser checks (95.78 seconds) and a production build (9.44 seconds). Focused checks passed: 42 bulk
approval, 19 independent approval audit and 86 Brain/context checks.
