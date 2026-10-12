@echo off
setlocal EnableExtensions DisableDelayedExpansion
title ClipFoundry - automatic setup
set "CF_BOOTSTRAP_SELF=%~f0"
set "CF_PS_LOADER=$raw = [IO.File]::ReadAllText($env:CF_BOOTSTRAP_SELF);"
set "CF_PS_LOADER=%CF_PS_LOADER% $m = [regex]::Match($raw, '(?ms)^# CF_POWERSHELL_BEGIN\r?\n(.*)\z');"
set "CF_PS_LOADER=%CF_PS_LOADER% if (-not $m.Success) { throw 'Launcher is incomplete.' };"
set "CF_PS_LOADER=%CF_PS_LOADER% & ([scriptblock]::Create($m.Groups[1].Value))"
powershell.exe -NoLogo -NoProfile -Command "%CF_PS_LOADER%"
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Setup did not finish. The error is shown above.
pause
exit /b 1

# CF_POWERSHELL_BEGIN
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$Commit = '7201047b795085f0cb608ea643efadf90074290c'
$ArchiveHash = '90a197126d586d0b5ebcbb46fc08a4cd18a5f38f00f555612e6a73853ae7881a'
$StartHash = '40cfe91a8c4818f6837d794beca0b610fa9d45863c381ea1dafd27c427e9f23c'
$ArchiveUrl = "https://github.com/landryschreiner33-coder/ClipForge-AI./archive/$Commit.zip"
$ArchivePrefix = "ClipForge-AI.-$Commit/"

function Test-OwnedInstall([string]$Root, [string]$Owner) {
    try {
        if ((Get-Item -LiteralPath $Root).Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false }
        $marker = Get-Content -LiteralPath (Join-Path $Root '.clipfoundry-oneclick.json') -Raw | ConvertFrom-Json
        if ($marker.kind -ne 'clipfoundry-oneclick-v1' -or $marker.commit -ne $Commit -or
            $marker.owner -ne $Owner) { return $false }
        return ((Get-FileHash -LiteralPath (Join-Path $Root 'start.bat') -Algorithm SHA256).Hash -eq $StartHash)
    } catch { return $false }
}

function Get-InstallRoots {
    $bases = @()
    if ($env:SystemDrive -match '^[A-Za-z]:$') { $bases += "$($env:SystemDrive)\CF14" }
    $local = [Environment]::GetFolderPath('LocalApplicationData')
    if ($local) { $bases += (Join-Path $local 'CF14') }
    foreach ($base in $bases) {
        foreach ($suffix in @('', '-Open', '-Open2', '-Open3', '-Open4')) {
            $candidate = $base + $suffix
            if ($candidate.Length -le 100) { $candidate }
        }
    }
}

function Find-Install([string[]]$Roots, [string]$Owner) {
    # Prefer an existing copy created by this launcher, regardless of other occupied folders.
    foreach ($root in $Roots) {
        if ((Test-Path -LiteralPath $root -PathType Container) -and (Test-OwnedInstall $root $Owner)) {
            return @{ Root = $root; Stage = $null }
        }
    }
    foreach ($root in $Roots) {
        if (Test-Path -LiteralPath $root) { continue }
        $parent = Split-Path -Parent $root
        $stage = Join-Path $parent ('CFsetup-' + [Guid]::NewGuid().ToString('N'))
        try {
            if (-not (Test-Path -LiteralPath $parent -PathType Container)) { continue }
            [void][IO.Directory]::CreateDirectory($stage)
            [IO.File]::WriteAllText((Join-Path $stage '.owned-stage'), $Owner)
            return @{ Root = $root; Stage = $stage }
        } catch {
            # Permission failures can fall back to the user's writable local application folder.
            if (Test-Path -LiteralPath (Join-Path $stage '.owned-stage')) {
                Remove-Item -LiteralPath $stage -Recurse -Force
            }
        }
    }
    throw 'Could not find a writable short installation folder. No existing installation was changed.'
}

function Expand-CheckedArchive([string]$Zip, [string]$App) {
    if ((Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash -ne $ArchiveHash) {
        throw 'The download did not match the verified build. Reopen this launcher to retry.'
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [void][IO.Directory]::CreateDirectory($App)
    $boundary = [IO.Path]::GetFullPath($App).TrimEnd([IO.Path]::DirectorySeparatorChar) +
        [IO.Path]::DirectorySeparatorChar
    $archive = [IO.Compression.ZipFile]::OpenRead($Zip)
    try {
        foreach ($entry in $archive.Entries) {
            if (-not $entry.FullName.StartsWith($ArchivePrefix, [StringComparison]::Ordinal)) {
                throw 'Unexpected archive folder.'
            }
            $relative = $entry.FullName.Substring($ArchivePrefix.Length)
            if (-not $relative) { continue }
            if ($relative.Contains('\') -or $relative.Contains(':') -or
                $relative -match '(^|/)\.\.(/|$)' -or [IO.Path]::IsPathRooted($relative)) {
                throw 'Unexpected archive path.'
            }
            $relativePath = $relative.Replace('/', [string][IO.Path]::DirectorySeparatorChar)
            $target = [IO.Path]::GetFullPath((Join-Path $App $relativePath))
            if (-not $target.StartsWith($boundary, [StringComparison]::OrdinalIgnoreCase)) {
                throw 'Archive path is outside the installation folder.'
            }
            if ($entry.FullName.EndsWith('/')) {
                [void][IO.Directory]::CreateDirectory($target)
                continue
            }
            [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
            $inputStream = $entry.Open()
            try {
                $outputStream = [IO.File]::Open($target, [IO.FileMode]::CreateNew,
                    [IO.FileAccess]::Write, [IO.FileShare]::None)
                try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose() }
            } finally { $inputStream.Dispose() }
        }
    } finally { $archive.Dispose() }
    if ((Get-FileHash -LiteralPath (Join-Path $App 'start.bat') -Algorithm SHA256).Hash -ne $StartHash -or
        -not (Test-Path -LiteralPath (Join-Path $App 'frontend/dist/index.html') -PathType Leaf)) {
        throw 'The installation is incomplete. Reopen this launcher to retry.'
    }
}

function Get-FreePort {
    foreach ($port in 8765..8775) {
        $listener = New-Object Net.Sockets.TcpListener ([Net.IPAddress]::Loopback), $port
        try {
            $listener.ExclusiveAddressUse = $true
            $listener.Start()
            return $port
        } catch { } finally { $listener.Stop() }
    }
    throw 'The ClipFoundry browser ports are busy. Close the other ClipFoundry window and reopen this launcher.'
}

function Invoke-AppLauncher([string]$Root, [bool]$SetupOnly) {
    $env:CF_BOOTSTRAP_START = Join-Path $Root 'start.bat'
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $env:ComSpec
    # A single environment expansion, with delayed expansion off, preserves &, %, ! and spaces in paths.
    if ($SetupOnly) { $info.Arguments = '/d /v:off /s /c ""%CF_BOOTSTRAP_START%" --setup-only"' }
    else { $info.Arguments = '/d /v:off /s /c ""%CF_BOOTSTRAP_START%""' }
    $info.WorkingDirectory = $Root
    $info.UseShellExecute = $false
    $process = [Diagnostics.Process]::Start($info)
    try {
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw 'Setup stopped. Keep the error above and reopen this launcher to retry.' }
    } finally { $process.Dispose() }
}

function Start-OneClick {
    if ($env:OS -ne 'Windows_NT') { throw 'This launcher is for Windows 10 or Windows 11.' }
    $owner = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $mutex = New-Object Threading.Mutex $false, ('Local\ClipFoundryOneClick-' + $owner)
    $locked = $false
    $install = $null
    try {
        try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
        if (-not $locked) {
            Write-Host 'ClipFoundry is already starting or running. Keep its first window open.'
            return
        }
        $install = Find-Install @(Get-InstallRoots) $owner
        if ($install.Stage) {
            Write-Host 'Downloading the verified ClipFoundry build...'
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor
                [Net.SecurityProtocolType]::Tls12
            $ProgressPreference = 'SilentlyContinue'
            $zip = Join-Path $install.Stage 'clipfoundry.zip'
            for ($attempt = 1; $attempt -le 3; $attempt++) {
                try {
                    Invoke-WebRequest -UseBasicParsing -Uri $ArchiveUrl -OutFile $zip -TimeoutSec 120
                    break
                } catch {
                    if ($attempt -eq 3) { throw 'Download failed. Check your connection and reopen this launcher.' }
                    Write-Host 'Download interrupted; retrying...'
                    Start-Sleep -Seconds 2
                }
            }
            Write-Host 'Preparing a fresh copy in a short folder...'
            $app = Join-Path $install.Stage 'app'
            Expand-CheckedArchive $zip $app
            $marker = @{ kind = 'clipfoundry-oneclick-v1'; commit = $Commit; owner = $owner } | ConvertTo-Json
            [IO.File]::WriteAllText((Join-Path $app '.clipfoundry-oneclick.json'), $marker)
            # Directory.Move refuses an existing destination; it cannot merge with or replace owner files.
            [IO.Directory]::Move($app, $install.Root)
        }
        $env:CLIPFOUNDRY_DATA = Join-Path $install.Root 'data'
        Remove-Item Env:CLIPFOUNDRY_WORKERS -ErrorAction SilentlyContinue
        Write-Host ('ClipFoundry folder: ' + $install.Root)
        Write-Host 'First-time setup can take several minutes. Keep this window open.'
        Invoke-AppLauncher $install.Root $true
        # Check after dependency downloads, so another app started during setup does not take our chosen port.
        $port = Get-FreePort
        $env:CLIPFOUNDRY_PORT = [string]$port
        Write-Host ('The app will open at http://127.0.0.1:' + $port)
        Invoke-AppLauncher $install.Root $false
    } finally {
        if ($install -and $install.Stage -and (Test-Path -LiteralPath (Join-Path $install.Stage '.owned-stage'))) {
            try { Remove-Item -LiteralPath $install.Stage -Recurse -Force } catch { }
        }
        if ($locked) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}

try { Start-OneClick } catch {
    Write-Host ('Setup could not finish: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
