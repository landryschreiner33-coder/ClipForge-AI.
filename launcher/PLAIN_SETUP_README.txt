ClipFoundry source setup

1. Save any edits and close the previous ClipFoundry/setup windows.
2. Right-click ClipFoundry-Source-Setup.zip and choose Extract All.
3. Open the extracted folder and double-click Open-ClipFoundry.cmd.
4. Keep its console open. Setup prepares a short installation folder and opens the app in your browser.
   Use this same CMD file for later sessions.

This package includes the exact verified app archive, a readable Python setup.py and a plain CMD launcher.
It uses your installed Python. It includes no custom EXE launcher or PowerShell loader and does not change
antivirus settings, execution policy, Windows trust/certificates, the firewall or publishing permission.
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

Application revision: 718358f30110ab871e21059177f83ccd9ea3d3a9
Included app.zip SHA-256: 2975806f4366bf2eba491b93e0634cf4f88083ce327657cf5ffc84456ac2d0cc
Setup verifies that hash and its known start.bat hash before installing or launching new app files.
The Python setup source is included for inspection. The archive is also inspectable with normal ZIP tools.

This app includes the finished-clip/YouTube scheduling repairs, automatic Brain guidance and phone dashboard.
In Missions, Why clips are waiting to post explains any remaining input, quality or YouTube permission hold.
Existing audience and automatic-publishing choices are preserved. No real upload is performed by setup.
