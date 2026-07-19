[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PortableDir,
    [switch]$KeepTemp
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

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

function Get-DesktopListenerProcessIds {
    return @(
        Get-NetTCPConnection `
            -LocalAddress "127.0.0.1" `
            -LocalPort 8787 `
            -State Listen `
            -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    )
}

function Wait-DesktopListenerOwner {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [int]$TimeoutSeconds = 15
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $owners = @(Get-DesktopListenerProcessIds)
        if ($owners.Count -eq 1 -and [int]$owners[0] -eq $ProcessId) {
            return
        }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "Desktop Web UI listener was not uniquely owned by process $ProcessId; owners: $($owners -join ', ')"
}

function Wait-DesktopListenerRelease {
    param([int]$TimeoutSeconds = 15)

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $owners = @(Get-DesktopListenerProcessIds)
        if ($owners.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "Desktop Web UI listener was not released; owners: $($owners -join ', ')"
}

function Wait-DesktopWebUi {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSeconds = 15
    )

    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(1)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    try {
        do {
            $response = $null
            try {
                $response = $client.GetAsync($Url).GetAwaiter().GetResult()
                $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                if ([int]$response.StatusCode -eq 200 -and $body.Contains("<title>dancing-log</title>")) {
                    return
                }
            }
            catch {
                # The frozen GUI may still be importing modules or binding its listener.
            }
            finally {
                if ($null -ne $response) {
                    $response.Dispose()
                }
            }
            Start-Sleep -Milliseconds 100
        } while ([DateTime]::UtcNow -lt $deadline)
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }

    throw "Desktop Web UI did not become ready at $Url"
}

function Get-SmokeBrowserUrls {
    param([Parameter(Mandatory = $true)][string]$LogPath)

    if (-not (Test-Path -LiteralPath $LogPath)) {
        return
    }
    Get-Content -LiteralPath $LogPath | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
}

function Wait-SmokeBrowserCount {
    param(
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][int]$MinimumCount,
        [int]$TimeoutSeconds = 10
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $urls = @(Get-SmokeBrowserUrls -LogPath $LogPath)
        if ($urls.Count -ge $MinimumCount) {
            return
        }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "Browser helper recorded $($urls.Count) URL(s); expected at least $MinimumCount"
}

function Stop-SmokeProcess {
    param([System.Diagnostics.Process]$Process)

    if ($null -eq $Process) {
        return
    }
    try {
        if (-not $Process.HasExited) {
            $Process.Kill()
            if (-not $Process.WaitForExit(5000)) {
                Write-Warning "Smoke process $($Process.Id) did not exit after Kill()"
            }
        }
    }
    catch {
        Write-Warning "Failed to stop smoke process $($Process.Id): $($_.Exception.Message)"
    }
}

function Invoke-DesktopSingleInstanceSmoke {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePortableRoot,
        [Parameter(Mandatory = $true)][string]$TestRoot,
        [Parameter(Mandatory = $true)][System.Text.Encoding]$TextEncoding
    )

    $desktopRoot = Join-Path $TestRoot "desktop-portable"
    $desktopExe = Join-Path $desktopRoot "DancingLog.exe"
    $browserLog = Join-Path $TestRoot "browser-open.log"
    $browserCommand = Join-Path $TestRoot "smoke-browser.cmd"
    $homeUrl = "http://127.0.0.1:8787/home"
    $processes = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()
    $previousBrowser = $env:BROWSER
    $previousBrowserLog = $env:DANCING_LOG_SMOKE_BROWSER_LOG

    New-Item -ItemType Directory -Force -Path $desktopRoot | Out-Null
    Copy-Item -Path (Join-Path $SourcePortableRoot "*") -Destination $desktopRoot -Recurse -Force
    [System.IO.File]::WriteAllText(
        $browserCommand,
        "@echo off`r`n>>`"%DANCING_LOG_SMOKE_BROWSER_LOG%`" echo %~1`r`nexit /b 0`r`n",
        $TextEncoding
    )

    try {
        $env:DANCING_LOG_SMOKE_BROWSER_LOG = $browserLog
        $env:BROWSER = "`"$browserCommand`" %s"

        $existingOwners = @(Get-DesktopListenerProcessIds)
        if ($existingOwners.Count -ne 0) {
            throw "Cannot run desktop smoke while 127.0.0.1:8787 is already listening; owners: $($existingOwners -join ', ')"
        }

        Write-Host "==> DancingLog.exe first desktop instance"
        $first = Start-Process `
            -FilePath $desktopExe `
            -WorkingDirectory $desktopRoot `
            -PassThru `
            -WindowStyle Hidden
        $processes.Add($first)
        Wait-DesktopListenerOwner -ProcessId $first.Id
        Wait-DesktopWebUi -Url $homeUrl
        Wait-SmokeBrowserCount -LogPath $browserLog -MinimumCount 1
        $beforeSecondCount = @(Get-SmokeBrowserUrls -LogPath $browserLog).Count

        Write-Host "==> DancingLog.exe second desktop instance"
        $secondTimer = [System.Diagnostics.Stopwatch]::StartNew()
        $second = Start-Process `
            -FilePath $desktopExe `
            -WorkingDirectory $desktopRoot `
            -PassThru `
            -WindowStyle Hidden
        $processes.Add($second)
        if (-not $second.WaitForExit(10000)) {
            throw "Second DancingLog.exe instance did not exit within 10 seconds"
        }
        $secondTimer.Stop()
        if ($second.ExitCode -ne 0) {
            throw "Second DancingLog.exe instance exited with code $($second.ExitCode)"
        }
        Wait-SmokeBrowserCount -LogPath $browserLog -MinimumCount ($beforeSecondCount + 1)
        $browserUrls = @(Get-SmokeBrowserUrls -LogPath $browserLog)
        if ($browserUrls[-1] -ne $homeUrl) {
            throw "Second DancingLog.exe opened '$($browserUrls[-1])' instead of '$homeUrl'"
        }
        Wait-DesktopListenerOwner -ProcessId $first.Id

        $first.Kill()
        if (-not $first.WaitForExit(10000)) {
            throw "First DancingLog.exe instance did not exit after Kill()"
        }
        Wait-DesktopListenerRelease

        Write-Host "==> DancingLog.exe replacement instance after mutex release"
        $replacement = Start-Process `
            -FilePath $desktopExe `
            -WorkingDirectory $desktopRoot `
            -PassThru `
            -WindowStyle Hidden
        $processes.Add($replacement)
        Wait-DesktopListenerOwner -ProcessId $replacement.Id
        Wait-DesktopWebUi -Url $homeUrl

        Stop-SmokeProcess -Process $replacement
        Wait-DesktopListenerRelease

        Write-Host "==> DancingLog.exe takeover after startup owner releases mutex"
        $createdStartupOwner = $false
        $startupOwner = [System.Threading.Mutex]::new(
            $true,
            "Local\DancingLog.DesktopTray.v1",
            [ref]$createdStartupOwner
        )
        if (-not $createdStartupOwner) {
            $startupOwner.Dispose()
            throw "Could not create synthetic desktop startup mutex owner"
        }
        $startupOwnerHeld = $true
        try {
            $beforeTakeoverCount = @(Get-SmokeBrowserUrls -LogPath $browserLog).Count
            $takeover = Start-Process `
                -FilePath $desktopExe `
                -WorkingDirectory $desktopRoot `
                -PassThru `
                -WindowStyle Hidden
            $processes.Add($takeover)

            Start-Sleep -Milliseconds 750
            $takeover.Refresh()
            if ($takeover.HasExited) {
                throw "Waiting DancingLog.exe exited before startup mutex release"
            }
            $prematureOwners = @(Get-DesktopListenerProcessIds)
            if ($prematureOwners.Count -ne 0) {
                throw "Waiting DancingLog.exe bound 8787 before startup mutex release; owners: $($prematureOwners -join ', ')"
            }

            $startupOwner.ReleaseMutex()
            $startupOwnerHeld = $false
            Wait-DesktopListenerOwner -ProcessId $takeover.Id
            Wait-DesktopWebUi -Url $homeUrl
            Wait-SmokeBrowserCount -LogPath $browserLog -MinimumCount ($beforeTakeoverCount + 1)
            $browserUrls = @(Get-SmokeBrowserUrls -LogPath $browserLog)
            if ($browserUrls[-1] -ne $homeUrl) {
                throw "Takeover DancingLog.exe opened '$($browserUrls[-1])' instead of '$homeUrl'"
            }
        }
        finally {
            if ($startupOwnerHeld) {
                $startupOwner.ReleaseMutex()
            }
            $startupOwner.Dispose()
        }

        Write-Host "Desktop single-instance and startup-takeover smoke passed; second exit: $($secondTimer.ElapsedMilliseconds) ms"
    }
    finally {
        foreach ($process in $processes) {
            Stop-SmokeProcess -Process $process
        }
        $env:BROWSER = $previousBrowser
        $env:DANCING_LOG_SMOKE_BROWSER_LOG = $previousBrowserLog
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
    Invoke-DesktopSingleInstanceSmoke `
        -SourcePortableRoot $PortableRoot `
        -TestRoot $SmokeRoot `
        -TextEncoding $utf8NoBom
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
