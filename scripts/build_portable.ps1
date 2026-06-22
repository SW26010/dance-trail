[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$Runtime = "win-x64",
    [string]$Python = "python",
    [string]$PyInstallerSpec = "pyinstaller>=6.0",
    [switch]$NoUv,
    [switch]$SkipTests,
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BuildRoot = Join-Path $RepoRoot "build"
$DistRoot = Join-Path $RepoRoot "dist"
$PyInstallerDist = Join-Path $BuildRoot "pyinstaller-dist"
$PyInstallerWork = Join-Path $BuildRoot "pyinstaller-work"
$PortableRoot = Join-Path $DistRoot "portable"
$ReleaseRoot = Join-Path $DistRoot "releases"

function Assert-InRepo {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $repoFullPath = [System.IO.Path]::GetFullPath($RepoRoot)
    if (-not $fullPath.StartsWith($repoFullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside repository: $fullPath"
    }
    return $fullPath
}

function Remove-InRepoDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = Assert-InRepo $Path
    if (Test-Path -LiteralPath $fullPath) {
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Command,
        [Parameter(Mandatory = $true)][string]$Label
    )

    Write-Host "==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Invoke-ProjectPython {
    param([string[]]$Arguments = @())

    if (-not $NoUv -and (Get-Command uv -ErrorAction SilentlyContinue)) {
        & uv run python @Arguments
    }
    else {
        & $Python @Arguments
    }
}

function Invoke-PyInstaller {
    param([string[]]$Arguments = @())

    if (-not $NoUv -and (Get-Command uv -ErrorAction SilentlyContinue)) {
        & uv run --with $PyInstallerSpec pyinstaller @Arguments
    }
    else {
        & $Python -m PyInstaller @Arguments
    }
}

function Compress-ReleaseArchive {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [int]$Attempts = 10,
        [int]$DelaySeconds = 2
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            if (Test-Path -LiteralPath $DestinationPath) {
                Remove-Item -LiteralPath $DestinationPath -Force
            }
            Compress-Archive -LiteralPath $SourcePath -DestinationPath $DestinationPath -Force -ErrorAction Stop
            return
        }
        catch {
            if ($attempt -eq $Attempts) {
                throw
            }
            Write-Host "Compress-Archive failed on attempt $attempt/$Attempts; retrying in $DelaySeconds seconds."
            Write-Host "  $($_.Exception.Message)"
            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

function Get-ProjectVersion {
    $match = Select-String -Path (Join-Path $RepoRoot "pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if (-not $match) {
        throw "Could not read project version from pyproject.toml"
    }
    return $match.Matches[0].Groups[1].Value
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Get-ProjectVersion
}
if ($Version.StartsWith("v", [System.StringComparison]::OrdinalIgnoreCase)) {
    $Version = $Version.Substring(1)
}

$AppName = "DancingLog"
$CliAppName = "DancingLogCli"
$ReleaseName = "$AppName-v$Version-$Runtime-portable"
$StageDir = Join-Path $PortableRoot $ReleaseName
$ZipPath = Join-Path $ReleaseRoot "$ReleaseName.zip"
$ChecksumPath = "$ZipPath.sha256"

Set-Location $RepoRoot

$pythonVersionCheck = "import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 'Python 3.14 or newer is required for release builds; got ' + sys.version.split()[0])"
Invoke-Checked { Invoke-ProjectPython -Arguments @("-c", $pythonVersionCheck) } "Check Python version"

if (-not $SkipTests) {
    Invoke-Checked { Invoke-ProjectPython -Arguments @("-m", "unittest", "discover") } "Run unit tests"
}

Remove-InRepoDirectory $PyInstallerDist
Remove-InRepoDirectory $PyInstallerWork
Remove-InRepoDirectory $StageDir
New-Item -ItemType Directory -Force $PyInstallerDist, $PyInstallerWork, $StageDir, $ReleaseRoot | Out-Null

$pyInstallerBaseArgs = @(
    "--clean",
    "--noconfirm",
    "--onedir",
    "--exclude-module", "imageio",
    "--exclude-module", "imageio_ffmpeg",
    "--distpath", $PyInstallerDist,
    "--workpath", $PyInstallerWork,
    "--specpath", $PyInstallerWork
)
$cliPyInstallerArgs = $pyInstallerBaseArgs + @(
    "--name", $CliAppName,
    "main.py"
)
$guiPyInstallerArgs = $pyInstallerBaseArgs + @(
    "--name", $AppName,
    "--windowed",
    "main.py"
)
Invoke-Checked { Invoke-PyInstaller -Arguments $cliPyInstallerArgs } "Build PyInstaller CLI onedir app"
Invoke-Checked { Invoke-PyInstaller -Arguments $guiPyInstallerArgs } "Build PyInstaller desktop tray onedir app"

$BuiltCliAppDir = Join-Path $PyInstallerDist $CliAppName
$BuiltAppDir = Join-Path $PyInstallerDist $AppName
if (-not (Test-Path -LiteralPath (Join-Path $BuiltCliAppDir "$CliAppName.exe"))) {
    throw "PyInstaller output is missing $CliAppName.exe"
}
if (-not (Test-Path -LiteralPath (Join-Path $BuiltAppDir "$AppName.exe"))) {
    throw "PyInstaller output is missing $AppName.exe"
}
Copy-Item -Path (Join-Path $BuiltCliAppDir "*") -Destination $StageDir -Recurse -Force
Copy-Item -Path (Join-Path $BuiltAppDir "*") -Destination $StageDir -Recurse -Force

Copy-Item -LiteralPath (Join-Path $RepoRoot "README.md") -Destination $StageDir -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "README.zh-CN.md") -Destination $StageDir -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "docs") -Destination (Join-Path $StageDir "docs") -Recurse -Force

$ConfigDir = Join-Path $StageDir "config"
$DataDir = Join-Path $StageDir "data"
$LogsDir = Join-Path $StageDir "logs"
New-Item -ItemType Directory -Force `
    $ConfigDir, `
    (Join-Path $DataDir "queued_self"), `
    (Join-Path $DataDir "archive"), `
    (Join-Path $LogsDir "captures"), `
    (Join-Path $LogsDir "runs"), `
    (Join-Path $LogsDir "source-vrc-logs") | Out-Null
Copy-Item -LiteralPath (Join-Path $RepoRoot "config\dancing-log.example.json") -Destination $ConfigDir -Force

$batEncoding = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText(
    (Join-Path $StageDir "sync-wanna.bat"),
    "@echo off`r`nsetlocal`r`ncd /d ""%~dp0""`r`nDancingLogCli.exe sync-wanna %*`r`n",
    $batEncoding
)
[System.IO.File]::WriteAllText(
    (Join-Path $StageDir "start-watch-vrc-log.bat"),
    "@echo off`r`nsetlocal`r`ncd /d ""%~dp0""`r`nDancingLogCli.exe watch-vrc-log --overlay-port 8765 %*`r`n",
    $batEncoding
)

if (-not $SkipSmoke) {
    Invoke-Checked {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "smoke_portable.ps1") -PortableDir $StageDir
    } "Smoke test portable app"
}

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
if (Test-Path -LiteralPath $ChecksumPath) {
    Remove-Item -LiteralPath $ChecksumPath -Force
}
Compress-ReleaseArchive -SourcePath $StageDir -DestinationPath $ZipPath
$hash = Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256
[System.IO.File]::WriteAllText(
    $ChecksumPath,
    "$($hash.Hash.ToLowerInvariant())  $(Split-Path $ZipPath -Leaf)`r`n",
    $batEncoding
)

Write-Host "Portable folder: $StageDir"
Write-Host "Release zip: $ZipPath"
Write-Host "Checksum: $ChecksumPath"
