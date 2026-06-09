[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PortableDir,
    [switch]$KeepTemp
)

$ErrorActionPreference = "Stop"

$PortableRoot = (Resolve-Path $PortableDir).Path
$ExePath = Join-Path $PortableRoot "DancingLog.exe"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "DancingLog.exe not found under portable directory: $PortableRoot"
}

$SmokeRoot = Join-Path $env:TEMP ("dancing-log-portable-smoke-" + [guid]::NewGuid().ToString("N"))
$DbPath = Join-Path $SmokeRoot "smoke.sqlite3"
$FavoritesPath = Join-Path $SmokeRoot "favorites.txt"
$ManifestDir = Join-Path $SmokeRoot "queued"
$VrcLogDir = Join-Path $SmokeRoot "vrc-logs"
$CaptureDir = Join-Path $SmokeRoot "captures"
$CacheTrackDir = Join-Path $SmokeRoot "wanna-cache\5038"

New-Item -ItemType Directory -Force $ManifestDir, $VrcLogDir, $CaptureDir, $CacheTrackDir | Out-Null

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($FavoritesPath, "5038`n", $utf8NoBom)
[System.IO.File]::WriteAllText(
    (Join-Path $CacheTrackDir "metadata.json"),
    '{"id":5038,"title":"Smoke Song","artist":"Smoke Artist"}',
    $utf8NoBom
)

function Invoke-Portable {
    param([string[]]$Arguments = @())

    $displayArguments = $Arguments | ForEach-Object {
        if ($_ -match '[\s"]') {
            '"' + ($_ -replace '"', '\"') + '"'
        }
        else {
            $_
        }
    }
    Write-Host "==> DancingLog.exe $($displayArguments -join ' ')"
    & $ExePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "DancingLog.exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Assert-PortableRejects {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$ExpectedOutput
    )

    $displayArguments = $Arguments | ForEach-Object {
        if ($_ -match '[\s"]') {
            '"' + ($_ -replace '"', '\"') + '"'
        }
        else {
            $_
        }
    }
    Write-Host "==> DancingLog.exe $($displayArguments -join ' ')"
    $output = & $ExePath @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        throw "DancingLog.exe $($Arguments -join ' ') unexpectedly succeeded"
    }
    if (($output -join "`n") -notlike "*$ExpectedOutput*") {
        throw "DancingLog.exe $($Arguments -join ' ') did not print expected output: $ExpectedOutput"
    }
}

try {
    Invoke-Portable -Arguments @("sync-wanna", "--offline", "--app-db", $DbPath, "--cache-dir", (Join-Path $SmokeRoot "wanna-cache"))
    Invoke-Portable -Arguments @("recommend", "--app-db", $DbPath, "-n", "1")
    Invoke-Portable -Arguments @("log", "--app-db", $DbPath, "--system", "wannadance", "5038")
    Invoke-Portable -Arguments @("import-favorites", "--app-db", $DbPath, "--system", "wannadance", $FavoritesPath)
    Invoke-Portable -Arguments @("sync-queued-self", "--app-db", $DbPath, "--manifest-dir", $ManifestDir, "--system", "wannadance")
    Invoke-Portable -Arguments @("watch-vrc-log", "--log-dir", $VrcLogDir, "--output-dir", $CaptureDir, "--app-db", $DbPath, "--no-source-archive", "--stop-after-idle-seconds", "0.1")
    Assert-PortableRejects -Arguments @("sample-frames") -ExpectedOutput "Usage:"
    Write-Host "Portable smoke test passed: $SmokeRoot"
}
finally {
    if (-not $KeepTemp -and (Test-Path -LiteralPath $SmokeRoot)) {
        $tempFullPath = [System.IO.Path]::GetFullPath($env:TEMP)
        $smokeFullPath = [System.IO.Path]::GetFullPath($SmokeRoot)
        if (-not $smokeFullPath.StartsWith($tempFullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to delete smoke directory outside TEMP: $smokeFullPath"
        }
        Remove-Item -LiteralPath $SmokeRoot -Recurse -Force
    }
}
