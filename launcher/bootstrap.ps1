$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$Commit = 'ec20aec76825a284393af00d812ec4a08a8beca3'
$ArchiveHash = '8f873e6acd924db131fdd600e1b4a83b9a20895eedb4ab77bc1fd21e7726d2f2'
$StartHash = '40cfe91a8c4818f6837d794beca0b610fa9d45863c381ea1dafd27c427e9f23c'
$ArchiveUrl = "https://github.com/landryschreiner33-coder/ClipForge-AI./archive/$Commit.zip"
$ArchivePrefix = "ClipForge-AI.-$Commit/"

# Known launcher revisions are the only older copies whose profile may be reused.
# Each installer adds its exact commit/start hash here; ordinary ZIP copies remain separate.
$KnownReleases = @{
    '28aee85b4ef239584da296cec900bc3d8dde4399' = '40cfe91a8c4818f6837d794beca0b610fa9d45863c381ea1dafd27c427e9f23c'
    '4838aa897e59b68a1365dd7ed7f4d60f52dfcc8c' = '40cfe91a8c4818f6837d794beca0b610fa9d45863c381ea1dafd27c427e9f23c'
    '718358f30110ab871e21059177f83ccd9ea3d3a9' = '40cfe91a8c4818f6837d794beca0b610fa9d45863c381ea1dafd27c427e9f23c'
    '7201047b795085f0cb608ea643efadf90074290c' = '40cfe91a8c4818f6837d794beca0b610fa9d45863c381ea1dafd27c427e9f23c'
    '987ebb288ae9097bedbd80d0adee2b3c05c4271f' = '40cfe91a8c4818f6837d794beca0b610fa9d45863c381ea1dafd27c427e9f23c'
    'd0b7102e8273cee068531da554c8d83f3fa43f8f' = '40cfe91a8c4818f6837d794beca0b610fa9d45863c381ea1dafd27c427e9f23c'
}
$KnownReleases[$Commit] = $StartHash

function Test-NoReparsePath([string]$Path) {
    try {
        $current = [IO.Path]::GetFullPath($Path)
        while ($current) {
            if ((Test-Path -LiteralPath $current) -and
                ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                return $false
            }
            $parent = [IO.Path]::GetDirectoryName($current)
            if ($parent -eq $current) { break }
            $current = $parent
        }
        return $true
    } catch { return $false }
}

function Get-MarkerValue($Marker, [string]$Name) {
    if ($null -eq $Marker) { return $null }
    $property = $Marker.PSObject.Properties[$Name]
    if ($property) { return $property.Value }
    return $null
}

function Get-ManagedMarker([string]$Root, [string]$Owner, [bool]$Strict = $false) {
    try {
        $markerFile = Join-Path $Root '.clipfoundry-oneclick.json'
        if (-not (Test-NoReparsePath $Root) -or -not (Test-NoReparsePath $markerFile)) { return $null }
        $marker = Get-Content -LiteralPath $markerFile -Raw | ConvertFrom-Json
    } catch { return $null }
    $kind = Get-MarkerValue $marker 'kind'
    if ($kind -notin @('clipfoundry-oneclick-v1', 'clipfoundry-oneclick-v2') -or
        (Get-MarkerValue $marker 'owner') -ne $Owner) { return $null }
    $revision = [string](Get-MarkerValue $marker 'commit')
    if (-not $KnownReleases.ContainsKey($revision)) {
        if ($Strict) { throw 'An existing managed app has an unrecognized revision. Its data was left unchanged.' }
        return $null
    }
    try {
        $startFile = Join-Path $Root 'start.bat'
        $matches = (Test-NoReparsePath $startFile) -and
            ((Get-FileHash -LiteralPath $startFile -Algorithm SHA256).Hash -eq $KnownReleases[$revision])
    } catch { $matches = $false }
    if (-not $matches) {
        if ($Strict) { throw 'An existing managed app could not be verified. Its data was left unchanged.' }
        return $null
    }
    return $marker
}

function Test-OwnedInstall([string]$Root, [string]$Owner) {
    $marker = Get-ManagedMarker $Root $Owner
    return ($null -ne $marker -and (Get-MarkerValue $marker 'commit') -eq $Commit)
}

function Get-InstallRoots {
    $bases = @()
    if ($env:SystemDrive -match '^[A-Za-z]:$') { $bases += "$($env:SystemDrive)\CF14" }
    $local = [Environment]::GetFolderPath('LocalApplicationData')
    if ($local) { $bases += (Join-Path $local 'CF14') }
    $candidates = @()
    foreach ($base in $bases) {
        # Existing five legacy names are recognized. Each new revision also has its own short name,
        # so upgrades do not run out of the old -Open slots or replace another app's files.
        foreach ($suffix in @('', '-Open', '-Open2', '-Open3', '-Open4')) { $candidates += $base + $suffix }
        $versioned = $base + '-' + $Commit.Substring(0, 12)
        $candidates += $versioned
        foreach ($suffix in 2..9) { $candidates += $versioned + '-' + $suffix }
        $parent = Split-Path -Parent $base
        $name = Split-Path -Leaf $base
        $pattern = '^' + [regex]::Escape($name) + '-[0-9a-f]{12}(-[2-9])?$'
        if (Test-Path -LiteralPath $parent -PathType Container) {
            $children = @(Get-ChildItem -LiteralPath $parent -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match $pattern } | Sort-Object Name)
            if ($children.Count -gt 512) { throw 'Too many managed app folders were found. No files were changed.' }
            foreach ($child in $children) { $candidates += $child.FullName }
        }
    }
    $seen = @()
    foreach ($candidate in $candidates) {
        if ($candidate.Length -le 100 -and $seen -notcontains $candidate) {
            $seen += $candidate
            $candidate
        }
    }
}

function Get-ManagedProfileRoot([string]$Root, [string]$Owner, [string[]]$Roots) {
    $marker = Get-ManagedMarker $Root $Owner $true
    if (-not $marker) { throw 'The managed app profile could not be verified. No existing data was changed.' }
    if ((Get-MarkerValue $marker 'kind') -eq 'clipfoundry-oneclick-v1') { $profileRoot = $Root }
    else { $profileRoot = [string](Get-MarkerValue $marker 'data_root') }
    if (-not $profileRoot -or -not [IO.Path]::IsPathRooted($profileRoot)) {
        throw 'The managed app profile path is invalid. No existing data was changed.'
    }
    $profileRoot = [IO.Path]::GetFullPath($profileRoot)
    $allowed = $false
    foreach ($candidate in $Roots) {
        if ($profileRoot -eq [IO.Path]::GetFullPath($candidate)) { $allowed = $true; break }
    }
    if (-not $allowed -or -not (Test-NoReparsePath (Join-Path $profileRoot 'data'))) {
        throw 'The managed app profile is outside a verified installation. No existing data was changed.'
    }
    $origin = Get-ManagedMarker $profileRoot $Owner $true
    if (-not $origin) { throw 'The original managed app profile could not be verified. No existing data was changed.' }
    if ((Get-MarkerValue $origin 'kind') -eq 'clipfoundry-oneclick-v2' -and
        [string](Get-MarkerValue $origin 'data_root') -ne $profileRoot) {
        throw 'The managed app profile has an unexpected chain. No existing data was changed.'
    }
    return $profileRoot
}

function Remove-OwnedStage([string]$Stage, [string]$Owner) {
    if (-not $Stage -or -not (Test-NoReparsePath $Stage)) { return }
    $stamp = Join-Path $Stage '.owned-stage'
    try {
        if (-not (Test-NoReparsePath $stamp) -or [IO.File]::ReadAllText($stamp) -cne $Owner) { return }
        Remove-Item -LiteralPath $Stage -Recurse -Force
    } catch { } # A cleanup failure must not replace the useful setup error or remove an unknown folder.
}

function Find-Install([string[]]$Roots, [string]$Owner) {
    $older = @()
    # Prefer this revision's verified copy; every revision points straight to the original profile.
    foreach ($root in $Roots) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        $marker = Get-ManagedMarker $root $Owner $true
        if (-not $marker) { continue }
        $profileRoot = Get-ManagedProfileRoot $root $Owner $Roots
        $entry = @{ Root = $root; DataRoot = $profileRoot; Stage = $null }
        if ((Get-MarkerValue $marker 'commit') -eq $Commit) { return $entry }
        $older += $entry
    }
    $profileRoot = $null
    foreach ($entry in $older) {
        if ($profileRoot -and $profileRoot -ne $entry.DataRoot) {
            throw 'More than one managed data folder was found. No profiles were combined or changed.'
        }
        $profileRoot = $entry.DataRoot
    }
    foreach ($root in $Roots) {
        if (Test-Path -LiteralPath $root) { continue }
        $parent = Split-Path -Parent $root
        $stage = Join-Path $parent ('CFsetup-' + [Guid]::NewGuid().ToString('N'))
        try {
            if (-not (Test-Path -LiteralPath $parent -PathType Container) -or
                -not (Test-NoReparsePath $parent)) { continue }
            [void][IO.Directory]::CreateDirectory($stage)
            [IO.File]::WriteAllText((Join-Path $stage '.owned-stage'), $Owner)
            if (-not $profileRoot) { $profileRoot = $root }
            return @{ Root = $root; DataRoot = $profileRoot; Stage = $stage }
        } catch {
            # Permission failures can fall back to the user's writable local application folder.
            Remove-OwnedStage $stage $Owner
        }
    }
    throw 'Could not find a writable short installation folder. No existing installation was changed.'
}

function Assert-ProfileStopped([string]$DataRoot, [string[]]$Roots, [string]$Owner) {
    $data = Join-Path $DataRoot 'data'
    $locks = Join-Path $data 'locks'
    if (-not (Test-NoReparsePath $locks)) { throw 'The app lock folder could not be verified. No data was changed.' }
    if (Test-Path -LiteralPath $locks -PathType Container) {
        foreach ($file in @(Get-ChildItem -LiteralPath $locks -Filter '*.lock' -File)) {
            $stream = $null
            $held = $false
            try {
                if (-not (Test-NoReparsePath $file.FullName)) { throw 'Unexpected app lock path.' }
                $stream = [IO.File]::Open($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite,
                    [IO.FileShare]::ReadWrite)
                $stream.Lock(0, 1)
                $held = $true
            } catch {
                throw 'ClipFoundry is still running. Close its app/setup windows, then open this installer again.'
            } finally {
                if ($held) { $stream.Unlock(0, 1) }
                if ($stream) { $stream.Dispose() }
            }
        }
    }
    # The byte locks also cover unattended restart gaps. Managed Python processes catch an ordinary
    # window before its worker host has started; no process is terminated and no command line is logged.
    if ($env:OS -eq 'Windows_NT') {
        $python = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
            Where-Object { $_.ExecutablePath })
        foreach ($root in $Roots) {
            if (-not (Get-ManagedMarker $root $Owner)) { continue }
            if ((Get-ManagedProfileRoot $root $Owner $Roots) -ne $DataRoot) { continue }
            $prefix = [IO.Path]::GetFullPath((Join-Path $root '.venv')) + [IO.Path]::DirectorySeparatorChar
            foreach ($process in $python) {
                if ($process.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
                    throw 'ClipFoundry is still running. Close its app/setup windows, then open this installer again.'
                }
            }
        }
    }
}

function Write-InstallMarker([string]$App, [string]$Root, [string]$DataRoot, [string]$Owner) {
    $marker = @{ kind = 'clipfoundry-oneclick-v2'; commit = $Commit; owner = $Owner;
        data_root = [IO.Path]::GetFullPath($DataRoot) } | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $App '.clipfoundry-oneclick.json'), $marker)
}

function Expand-CheckedArchive([string]$Zip, [string]$App) {
    if ((Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash -ne $ArchiveHash) {
        throw 'The app archive did not match the verified build. Download a fresh installer and retry.'
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

function Get-AppArchive([string]$Stage) {
    if ($env:CF_OPEN_ARCHIVE) {
        if (-not (Test-Path -LiteralPath $env:CF_OPEN_ARCHIVE -PathType Leaf)) {
            throw 'The included app archive is missing. Download a fresh installer and retry.'
        }
        Write-Host 'Using the app files included in this installer...'
        return $env:CF_OPEN_ARCHIVE
    }
    # Only the optional BAT launcher needs to fetch app files; the EXE always supplies its checked payload.
    Write-Host 'Downloading the verified ClipFoundry build...'
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor
        [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = 'SilentlyContinue'
    $zip = Join-Path $Stage 'clipfoundry.zip'
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $ArchiveUrl -OutFile $zip -TimeoutSec 120
            return $zip
        } catch {
            $reason = $_.Exception.GetBaseException().Message
            if ($attempt -eq 3) { throw ('App archive download failed after 3 attempts: ' + $reason) }
            Write-Host ('Archive download attempt ' + $attempt + ' failed: ' + $reason + ' Retrying...')
            Start-Sleep -Seconds 2
        }
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
        $roots = @(Get-InstallRoots)
        $install = Find-Install $roots $owner
        Assert-ProfileStopped $install.DataRoot $roots $owner
        if ($install.Stage) {
            $zip = Get-AppArchive $install.Stage
            Write-Host 'Preparing a fresh copy in a short folder...'
            $app = Join-Path $install.Stage 'app'
            Expand-CheckedArchive $zip $app
            Write-InstallMarker $app $install.Root $install.DataRoot $owner
            # Directory.Move refuses an existing destination; it cannot merge with or replace owner files.
            [IO.Directory]::Move($app, $install.Root)
        }
        $env:CLIPFOUNDRY_DATA = Join-Path $install.DataRoot 'data'
        Remove-Item Env:CLIPFOUNDRY_WORKERS -ErrorAction SilentlyContinue
        Write-Host ('ClipFoundry folder: ' + $install.Root)
        Write-Host ('Your saved Brain, accounts and clips: ' + $env:CLIPFOUNDRY_DATA)
        Write-Host 'First-time setup can take several minutes. Keep this window open.'
        Invoke-AppLauncher $install.Root $true
        # Check after dependency downloads, so another app started during setup does not take our chosen port.
        Assert-ProfileStopped $install.DataRoot $roots $owner
        $port = Get-FreePort
        $env:CLIPFOUNDRY_PORT = [string]$port
        Write-Host ('The app will open at http://127.0.0.1:' + $port)
        Invoke-AppLauncher $install.Root $false
    } finally {
        if ($install -and $install.Stage) { Remove-OwnedStage $install.Stage $owner }
        if ($locked) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}

try { Start-OneClick } catch {
    Write-Host ('Setup could not finish: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
