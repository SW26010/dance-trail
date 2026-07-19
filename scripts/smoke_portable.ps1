[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PortableDir,
    [switch]$KeepTemp
)

$ErrorActionPreference = "Stop"

$PortableRoot = (Resolve-Path $PortableDir).Path
$ExePath = Join-Path $PortableRoot "DancingLog.exe"
$CliExePath = Join-Path $PortableRoot "DancingLogCli.exe"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "DancingLog.exe not found under portable directory: $PortableRoot"
}
if (-not (Test-Path -LiteralPath $CliExePath)) {
    throw "DancingLogCli.exe not found under portable directory: $PortableRoot"
}

$SmokeRoot = Join-Path $env:TEMP ("dancing-log-portable-smoke-" + [guid]::NewGuid().ToString("N"))
$DbPath = Join-Path $SmokeRoot "smoke.sqlite3"
$FavoritesPath = Join-Path $SmokeRoot "favorites.txt"
$ManifestDir = Join-Path $SmokeRoot "queued"
$VrcLogDir = Join-Path $SmokeRoot "vrc-logs"
$CaptureDir = Join-Path $SmokeRoot "captures"
$CacheTrackDir = Join-Path $SmokeRoot "wanna-cache\5038"
$WebUiPortableRoot = Join-Path $SmokeRoot "webui-portable"
$WebUiProcess = $null

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
    Write-Host "==> DancingLogCli.exe $($displayArguments -join ' ')"
    & $CliExePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "DancingLogCli.exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
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
    Write-Host "==> DancingLogCli.exe $($displayArguments -join ' ')"
    $output = & $CliExePath @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        throw "DancingLogCli.exe $($Arguments -join ' ') unexpectedly succeeded"
    }
    if (($output -join "`n") -notlike "*$ExpectedOutput*") {
        throw "DancingLogCli.exe $($Arguments -join ' ') did not print expected output: $ExpectedOutput"
    }
}

function Get-FreeTcpPort {
    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    $listener.Start()
    try {
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

function Start-And-Test-PortableWebUi {
    Copy-Item -LiteralPath $PortableRoot -Destination $WebUiPortableRoot -Recurse
    $webUiExe = Join-Path $WebUiPortableRoot "DancingLog.exe"
    $webUiPort = Get-FreeTcpPort
    $baseUrl = "http://127.0.0.1:$webUiPort"
    $script:WebUiProcess = Start-Process `
        -FilePath $webUiExe `
        -ArgumentList @("webui", "--no-open", "--port", [string]$webUiPort) `
        -PassThru `
        -WindowStyle Hidden

    $homeResponse = $null
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        if ($script:WebUiProcess.HasExited) {
            throw "Frozen Web UI exited before becoming ready"
        }
        try {
            $homeResponse = Invoke-WebRequest `
                -Uri "$baseUrl/home" `
                -UseBasicParsing `
                -TimeoutSec 1
            break
        }
        catch {
            Start-Sleep -Milliseconds 100
        }
    }
    if ($null -eq $homeResponse) {
        throw "Frozen Web UI did not become ready within 20 seconds"
    }
    $homeContentType = [string]$homeResponse.Headers["Content-Type"]
    if (
        $homeResponse.StatusCode -ne 200 -or
        $homeContentType -notlike "text/html*" -or
        $homeResponse.Content.Length -lt 100
    ) {
        throw "Frozen Web UI /home response is incomplete"
    }

    $assetResponse = Invoke-WebRequest `
        -Uri "$baseUrl/assets/app.js" `
        -UseBasicParsing `
        -TimeoutSec 5
    $assetContentType = [string]$assetResponse.Headers["Content-Type"]
    if (
        $assetResponse.StatusCode -ne 200 -or
        $assetContentType -notlike "text/javascript*" -or
        $assetResponse.Content.Length -lt 1000
    ) {
        throw "Frozen Web UI /assets/app.js response is incomplete"
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
    Start-And-Test-PortableWebUi
    Write-Host "Portable smoke test passed: $SmokeRoot"
}
finally {
    if ($null -ne $WebUiProcess -and -not $WebUiProcess.HasExited) {
        Stop-Process -Id $WebUiProcess.Id -Force
        $WebUiProcess.WaitForExit(5000)
    }
    if (-not $KeepTemp -and (Test-Path -LiteralPath $SmokeRoot)) {
        $tempFullPath = [System.IO.Path]::GetFullPath($env:TEMP)
        $smokeFullPath = [System.IO.Path]::GetFullPath($SmokeRoot)
        if (-not $smokeFullPath.StartsWith($tempFullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to delete smoke directory outside TEMP: $smokeFullPath"
        }
        Remove-Item -LiteralPath $SmokeRoot -Recurse -Force
    }
}
