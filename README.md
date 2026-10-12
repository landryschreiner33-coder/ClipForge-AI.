# ClipFoundry: automatic Windows setup

Download **Open-ClipFoundry.exe** and double-click it. Keep its window open while
first-time setup finishes. The app then opens in your browser. A self-contained
Open-ClipFoundry.bat is also provided as an alternative.
Use the same launcher again for later sessions.

It downloads the verified merged app into a fresh short folder automatically,
normally C:\CF14. Occupied folders are skipped. If drive-root access is unavailable,
it tries your writable local application folder. Installation roots stay at most
100 characters long, avoiding the original nested-folder dependency error.

Existing folders, data and failed virtual environments are left alone. This is a
separate new copy: accounts and settings from another installation are not
migrated. Subsequent launches reuse only the launcher's own revision/user marker
and matching start.bat. No administrator access, registry changes, scheduled task
or automatic publishing consent is needed or granted.

An existing Python installation and internet connection are required. The usual
start.bat installs the existing dependencies and GPU libraries; FFmpeg requirements
are unchanged. Initial downloads can take several minutes. A free loopback port
from 8765 through 8775 is selected after setup. One instance per Windows user runs
at once. Failed setup can be retried by reopening the launcher.

## Build and checks

App revision: 7201047b795085f0cb608ea643efadf90074290c.
Verified ZIP SHA-256: 90a197126d586d0b5ebcbb46fc08a4cd18a5f38f00f555612e6a73853ae7881a.

The launcher verifies this hash before extracting, strips the ZIP wrapper folder,
rejects paths outside its own fresh staging directory, and refuses to install over
an existing destination. Cleanup touches only its own staging files.

21 portable checks passed using PowerShell 7.4.6 on Linux: extraction, checksum
refusal, owner-data preservation, repeat-open reuse, permission fallback,
destination collision, path traversal refusal and occupied-port selection.
All 416 extracted app file hashes match. The embedded PowerShell parser and an
independent CMD/PowerShell 5 compatibility review passed. Native Windows execution
was not available for verification. Default-branch app code and GPU pins are
unchanged by this standalone launcher delivery.

The Windows x64 executable is a small Go bootstrap containing the same checked
PowerShell setup script. Its complete source is in launcher/. It uses only the Go
standard library, runs without elevation and does not change execution-policy
settings. It is unsigned. Native Windows execution remains unverified here.

Executable SHA-256: 7995f1d97ce548ea9a3fe565f8112277f19c29b101432acc6d3900c598af5e69.
