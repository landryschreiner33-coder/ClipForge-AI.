param([string]$ArchivePath = (Join-Path $PSScriptRoot 'app.zip'))
$ErrorActionPreference = 'Stop'
$body = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'bootstrap.ps1'))
$errors = $null
$tokens = $null
$ast = [Management.Automation.Language.Parser]::ParseInput($body, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$definitions = $body.Substring(0, $body.LastIndexOf('try { Start-OneClick } catch {'))
. ([scriptblock]::Create($definitions))
$test = Join-Path ([IO.Path]::GetTempPath()) ('CFchecks-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($test)
$passed = 0
function Check($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:passed++
    Write-Host ('PASS: ' + $Message)
}
function Refuses($Block, [string]$Message) {
    $failed = $false
    try { & $Block } catch { $failed = $true }
    Check $failed $Message
}

try {
    Check ($errors.Count -eq 0) 'Embedded PowerShell parses cleanly'
    $zip = $ArchivePath
    $app = Join-Path $test 'expanded'
    Expand-CheckedArchive $zip $app
    Check (Test-Path -LiteralPath (Join-Path $app 'start.bat')) 'Wrapper folder is stripped'
    Check (-not (Test-Path -LiteralPath (Join-Path $app $ArchivePrefix))) 'No nested generated project folder'
    Check (-not (Test-Path -LiteralPath (Join-Path $app '.venv'))) 'Fresh extraction has no broken virtual environment'
    Check (-not (Test-Path -LiteralPath (Join-Path $app 'data'))) 'Fresh extraction has no existing owner data'

    $archive = [IO.Compression.ZipFile]::OpenRead($zip)
    $files = 0
    try {
        foreach ($entry in $archive.Entries) {
            $relative = $entry.FullName.Substring($ArchivePrefix.Length)
            if (-not $relative -or $entry.FullName.EndsWith('/')) { continue }
            $a = $entry.Open()
            try {
                $hash = [Security.Cryptography.SHA256]::Create()
                try { $expected = [BitConverter]::ToString($hash.ComputeHash($a)).Replace('-', '') }
                finally { $hash.Dispose() }
            } finally { $a.Dispose() }
            $actual = (Get-FileHash -LiteralPath (Join-Path $app $relative) -Algorithm SHA256).Hash
            if ($expected -ne $actual) { throw ('Extracted file differs: ' + $relative) }
            $files++
        }
    } finally { $archive.Dispose() }
    Check ($files -gt 300) ('All ' + $files + ' archive file hashes match')

    $bad = Join-Path $test 'bad.zip'
    [IO.File]::WriteAllText($bad, 'not the verified archive')
    Refuses { Expand-CheckedArchive $bad (Join-Path $test 'rejected-hash') } 'Bad checksum is refused'
    Check (-not (Test-Path -LiteralPath (Join-Path $test 'rejected-hash'))) 'Bad checksum writes no app files'

    $script:networkCalls = 0
    function Invoke-WebRequest { $script:networkCalls++; throw 'Fake inaccessible GitHub archive (404)' }
    $env:CF_OPEN_ARCHIVE = $zip
    $selected = Get-AppArchive $test
    Check ($selected -eq $zip) 'Bundled payload is selected directly'
    Check ($networkCalls -eq 0) 'Bundled install makes zero app download requests'
    $env:CF_OPEN_ARCHIVE = Join-Path $test 'missing-included.zip'
    Refuses { Get-AppArchive $test } 'Missing bundled archive is reported without network fallback'
    Check ($networkCalls -eq 0) 'Missing bundle does not invoke downloader'
    $env:CF_OPEN_ARCHIVE = $bad
    $corrupt = Get-AppArchive $test
    $action = { Expand-CheckedArchive $corrupt (Join-Path $test 'corrupt-bundle-app') }
    Refuses $action 'Corrupt bundled archive is refused'
    Check ($networkCalls -eq 0) 'Corrupt bundle does not invoke downloader'
    Check (-not (Test-Path -LiteralPath (Join-Path $test 'corrupt-bundle-app'))) 'Corrupt bundle writes no app files'
    Remove-Item Env:CF_OPEN_ARCHIVE
    $reason = ''
    try { Get-AppArchive $test } catch { $reason = $_.Exception.Message }
    Check ($networkCalls -eq 3) 'Optional network fallback uses exactly three attempts'
    Check ($reason.Contains('Fake inaccessible GitHub archive (404)')) 'Fallback reports actual cause'
    Remove-Item Function:Invoke-WebRequest

    $unknown = Join-Path $test 'existing-owner-app'
    [void][IO.Directory]::CreateDirectory($unknown)
    [IO.File]::WriteAllText((Join-Path $unknown 'data.txt'), 'existing owner data')
    $target = Join-Path $test 'new-root'
    $selection = Find-Install @($unknown, $target) 'test-owner'
    Check ($selection.Root -eq $target) 'Unknown existing installation is skipped'
    $condition = ((Get-Content -LiteralPath (Join-Path $unknown 'data.txt') -Raw) -eq 'existing owner data')
    Check $condition 'Owner data is preserved'
    Check (Test-Path -LiteralPath (Join-Path $selection.Stage '.owned-stage')) 'Only an owned fresh stage is created'
    Remove-Item -LiteralPath $selection.Stage -Recurse -Force

    $nullMarker = Join-Path $test 'null-marker'
    [void][IO.Directory]::CreateDirectory($nullMarker)
    [IO.File]::WriteAllText((Join-Path $nullMarker '.clipfoundry-oneclick.json'), 'null')
    Check (-not (Test-OwnedInstall $nullMarker 'test-owner')) 'A JSON null marker is treated as an unknown folder'
    $foreignStage = Join-Path $test 'foreign-stage'
    [void][IO.Directory]::CreateDirectory($foreignStage)
    [IO.File]::WriteAllText((Join-Path $foreignStage '.owned-stage'), 'other-owner')
    [IO.File]::WriteAllText((Join-Path $foreignStage 'keep.txt'), 'owner stage')
    Remove-OwnedStage $foreignStage 'test-owner'
    $condition = ((Get-Content -LiteralPath (Join-Path $foreignStage 'keep.txt') -Raw) -ceq 'owner stage')
    Check $condition 'Cleanup refuses another owner stage'
    [IO.File]::WriteAllText((Join-Path $foreignStage '.owned-stage'), 'test-owner')
    Remove-OwnedStage $foreignStage 'test-owner'
    Check (-not (Test-Path -LiteralPath $foreignStage)) 'Cleanup removes only the verified owned stage'

    $marker = @{ kind = 'clipfoundry-oneclick-v1'; commit = $Commit; owner = 'test-owner' } | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $app '.clipfoundry-oneclick.json'), $marker)
    Check (Test-OwnedInstall $app 'test-owner') 'Verified owned installation is reusable'
    Check (-not (Test-OwnedInstall $app 'other-owner')) 'Different user marker is refused'
    $reused = Find-Install @($unknown, $app, $target) 'test-owner'
    Check ($reused.Root -eq $app -and -not $reused.Stage) 'Repeat open reuses the same owned installation'

    $existing = Join-Path $test 'race-target'
    [void][IO.Directory]::CreateDirectory($existing)
    [IO.File]::WriteAllText((Join-Path $existing 'data.txt'), 'preserve')
    $stageApp = Join-Path $test 'race-stage'
    [void][IO.Directory]::CreateDirectory($stageApp)
    [IO.File]::WriteAllText((Join-Path $stageApp 'new.txt'), 'new app')
    $action = { [IO.Directory]::Move($stageApp, $existing) }
    Refuses $action 'Concurrent existing destination cannot be merged or overwritten'
    $condition = ((Get-Content -LiteralPath (Join-Path $existing 'data.txt') -Raw) -eq 'preserve')
    Check $condition 'Concurrent owner data remains intact'
    $condition = (-not (Test-Path -LiteralPath (Join-Path $existing 'new.txt')))
    Check $condition 'No source file is nested into an existing folder'

    $fallback = Find-Install @((Join-Path $test 'missing-parent/CF14'), $target) 'test-owner'
    Check ($fallback.Root -eq $target) 'Missing parent falls back to a writable root'
    Remove-Item -LiteralPath $fallback.Stage -Recurse -Force

    $traversal = Join-Path $test 'traversal.zip'
    $a = [IO.Compression.ZipFile]::Open($traversal, [IO.Compression.ZipArchiveMode]::Create)
    try { [void]$a.CreateEntry($ArchivePrefix + '../../escape.txt') } finally { $a.Dispose() }
    $originalHash = $ArchiveHash
    try {
        $ArchiveHash = (Get-FileHash -LiteralPath $traversal -Algorithm SHA256).Hash
        $action = { Expand-CheckedArchive $traversal (Join-Path $test 'traversal-app') }
        Refuses $action 'Extraction also rejects parent traversal'
        $condition = (-not (Test-Path -LiteralPath (Join-Path ([IO.Path]::GetTempPath()) 'escape.txt')))
        Check $condition 'Traversal cannot write outside the installation'
    } finally { $ArchiveHash = $originalHash }

    # Simulate successive releases with actual verified archive files. Only the release identity changes;
    # the saved profile, credentials, owner media and virtual environment must remain byte-for-byte intact.
    $oldCommit = $Commit
    $oldHash = $StartHash
    # The production upgrade must recognize the earlier bundled v1 app, not only this release's marker.
    $legacyCommit = '7201047b795085f0cb608ea643efadf90074290c'
    $legacyHash = $KnownReleases[$legacyCommit]
    if ((Get-FileHash -LiteralPath (Join-Path $app 'start.bat') -Algorithm SHA256).Hash -ne $legacyHash) {
        throw 'This upgrade regression needs the checked legacy start.bat fixture when launcher bytes change.'
    }
    $legacyMarker = @{ kind = 'clipfoundry-oneclick-v1'; commit = $legacyCommit; owner = 'test-owner' } |
        ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $app '.clipfoundry-oneclick.json'), $legacyMarker)
    $oldData = Join-Path $app 'data'
    [void][IO.Directory]::CreateDirectory((Join-Path $oldData 'projects'))
    [void][IO.Directory]::CreateDirectory((Join-Path $app '.venv'))
    $kept = @{
        'data/clipfoundry.db' = 'Brain lessons, examples and database';
        'data/accounts.secret' = 'synthetic DPAPI-encrypted account fixture';
        'data/projects/owner.mp4' = 'synthetic existing media';
        '.venv/owner-environment.txt' = 'original virtual environment stays in place'
    }
    foreach ($relative in $kept.Keys) { [IO.File]::WriteAllText((Join-Path $app $relative), $kept[$relative]) }
    $newRoot = Join-Path $test 'new-release'
    $nextRoot = Join-Path $test 'next-release'
    $Commit = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    $KnownReleases[$Commit] = $StartHash
    $upgrade = Find-Install @($unknown, $app, $newRoot) 'test-owner'
    $condition = ($upgrade.Root -eq $newRoot -and $upgrade.DataRoot -eq $app)
    Check $condition 'New release reuses the verified original profile'
    Check ($null -ne $upgrade.Stage) 'Upgrade stages a fresh code folder'
    $upgradeApp = Join-Path $upgrade.Stage 'app'
    [void][IO.Directory]::CreateDirectory($upgradeApp)
    [IO.File]::Copy((Join-Path $app 'start.bat'), (Join-Path $upgradeApp 'start.bat'))
    Write-InstallMarker $upgradeApp $newRoot $upgrade.DataRoot 'test-owner'
    [IO.Directory]::Move($upgradeApp, $newRoot)
    Remove-Item -LiteralPath $upgrade.Stage -Recurse -Force
    $same = Find-Install @($app, $newRoot, $nextRoot) 'test-owner'
    $condition = ($same.Root -eq $newRoot -and -not $same.Stage -and $same.DataRoot -eq $app)
    Check $condition 'Retry reuses new code and original profile'
    $condition = (-not (Test-Path -LiteralPath (Join-Path $newRoot '.venv')))
    Check $condition 'Upgrade never moves or copies an old virtual environment'
    Check (-not (Test-Path -LiteralPath (Join-Path $newRoot 'data'))) 'Upgrade does not copy or fork owner data'
    foreach ($relative in $kept.Keys) {
        $condition = ((Get-Content -LiteralPath (Join-Path $app $relative) -Raw) -ceq $kept[$relative])
        Check $condition ('Upgrade preserves ' + $relative)
    }
    $Commit = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
    $KnownReleases[$Commit] = $StartHash
    $second = Find-Install @($app, $newRoot, $nextRoot) 'test-owner'
    $condition = ($second.DataRoot -eq $app -and $second.Root -eq $nextRoot)
    Check $condition 'A second upgrade still points straight to original profile'
    Remove-Item -LiteralPath $second.Stage -Recurse -Force

    $safeMarker = Get-Content -LiteralPath (Join-Path $newRoot '.clipfoundry-oneclick.json') -Raw
    $outside = Join-Path $test 'outside-owner-folder'
    [void][IO.Directory]::CreateDirectory($outside)
    [IO.File]::WriteAllText((Join-Path $outside 'keep.txt'), 'do not touch')
    Write-InstallMarker $newRoot $newRoot $outside 'test-owner'
    Refuses { Find-Install @($app, $newRoot, $nextRoot) 'test-owner' } 'A marker cannot point to an unknown data folder'
    $condition = ((Get-Content -LiteralPath (Join-Path $outside 'keep.txt') -Raw) -ceq 'do not touch')
    Check $condition 'Invalid profile path leaves outside owner files intact'
    [IO.File]::WriteAllText((Join-Path $newRoot '.clipfoundry-oneclick.json'), $safeMarker)
    [IO.File]::AppendAllText((Join-Path $newRoot 'start.bat'), 'tampered')
    $action = { Find-Install @($app, $newRoot, $nextRoot) 'test-owner' }
    Refuses $action 'Tampered managed code stops upgrade rather than losing its profile'
    [IO.File]::Copy((Join-Path $app 'start.bat'), (Join-Path $newRoot 'start.bat'), $true)
    $unknownRevision = @{ kind = 'clipfoundry-oneclick-v1'; commit = ('c' * 40); owner = 'test-owner' } | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $newRoot '.clipfoundry-oneclick.json'), $unknownRevision)
    $action = { Find-Install @($app, $newRoot, $nextRoot) 'test-owner' }
    Refuses $action 'Unrecognized managed revisions are not silently replaced with empty profiles'
    [IO.File]::WriteAllText((Join-Path $newRoot '.clipfoundry-oneclick.json'), $safeMarker)
    $roots = @($app, $newRoot, $nextRoot)
    Assert-ProfileStopped $app $roots 'test-owner'
    Check $true 'Inactive profile can be opened without modifying its data'

    # FileStream byte-range locking maps to the same Windows lock primitive used by Python's msvcrt.
    # A separate process is essential: locks held by the current process may be re-entrant on POSIX.
    $lockDir = Join-Path $oldData 'locks'
    [void][IO.Directory]::CreateDirectory($lockDir)
    $lockFile = Join-Path $lockDir 'worker-host.lock'
    [IO.File]::WriteAllText($lockFile, '0')
    $readyFile = Join-Path $test 'lock-ready'
    $stopFile = Join-Path $test 'lock-stop'
    $childScript = Join-Path $test 'hold-lock.ps1'
    $childBody = @'
$ErrorActionPreference = 'Stop'
$stream = [IO.File]::Open($env:CF_TEST_LOCK, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
try {
    $stream.Lock(0, 1)
    [IO.File]::WriteAllText($env:CF_TEST_READY, 'ready')
    while (-not [IO.File]::Exists($env:CF_TEST_STOP)) { Start-Sleep -Milliseconds 50 }
} finally { $stream.Unlock(0, 1); $stream.Dispose() }
'@
    [IO.File]::WriteAllText($childScript, $childBody)
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = (Get-Process -Id $PID).Path
    $info.Arguments = '-NoLogo -NoProfile -File "' + $childScript + '"'
    $info.UseShellExecute = $false
    $info.EnvironmentVariables['CF_TEST_LOCK'] = $lockFile
    $info.EnvironmentVariables['CF_TEST_READY'] = $readyFile
    $info.EnvironmentVariables['CF_TEST_STOP'] = $stopFile
    $child = [Diagnostics.Process]::Start($info)
    try {
        $deadline = [DateTime]::UtcNow.AddSeconds(10)
        while (-not (Test-Path -LiteralPath $readyFile) -and [DateTime]::UtcNow -lt $deadline) {
            Start-Sleep -Milliseconds 50
        }
        Check (Test-Path -LiteralPath $readyFile) 'Independent process holds the profile byte lock'
        $action = { Assert-ProfileStopped $app $roots 'test-owner' }
        Refuses $action 'A running worker profile blocks setup without terminating it'
        Check (-not $child.HasExited) 'Blocking upgrade leaves the active worker process alive'
    } finally {
        [IO.File]::WriteAllText($stopFile, 'stop')
        if (-not $child.WaitForExit(10000)) { $child.Kill(); $child.WaitForExit() }
        $child.Dispose()
    }
    Assert-ProfileStopped $app $roots 'test-owner'
    Check $true 'An exited worker leaves no stale upgrade block'
    foreach ($relative in $kept.Keys) {
        $condition = ((Get-Content -LiteralPath (Join-Path $app $relative) -Raw) -ceq $kept[$relative])
        Check $condition ('Lock probes preserve ' + $relative)
    }
    $Commit = $oldCommit
    $StartHash = $oldHash

    $port = Get-FreePort
    $listener = New-Object Net.Sockets.TcpListener ([Net.IPAddress]::Loopback), $port
    try {
        $listener.ExclusiveAddressUse = $true
        $listener.Start()
        Check ((Get-FreePort) -ne $port) 'An occupied browser port is skipped'
    } finally { $listener.Stop() }
    Write-Host ('All ' + $passed + ' portable launcher checks passed. Native Windows invocation remains unverified.')
} finally {
    Remove-Item -LiteralPath $test -Recurse -Force
}
