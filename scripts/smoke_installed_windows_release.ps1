$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BundleRoot = Join-Path $Root "src-tauri\target\release\bundle"
$NsisRoot = Join-Path $BundleRoot "nsis"
$BuiltBackendExe = Join-Path $Root "src-tauri\resources\backend\ai-marketing-backend.exe"
$BackendChecksumFile = Join-Path $Root "backend-checksum.sha256"
$RunSuffix = if ($env:GITHUB_RUN_ID) { $env:GITHUB_RUN_ID } else { [Guid]::NewGuid().ToString("N") }
$InstallDir = Join-Path $env:TEMP "ai-marketing-department-clean-install-$RunSuffix"
$RuntimeDir = Join-Path $env:APPDATA "AI-Marketing-Department\runtime"
$StateFile = Join-Path $RuntimeDir "backend_instance.json"
$RetryConfigDir = Join-Path $env:TEMP "ai-marketing-installed-retry-config-$RunSuffix"
$RetryBackendPort = 18769
$RetryMockPort = 18770

Write-Host "== Clean-install Windows release certification ==" -ForegroundColor Cyan

$installer = Get-ChildItem -Path $NsisRoot -Filter "*.exe" -File -ErrorAction Stop |
    Sort-Object Length -Descending |
    Select-Object -First 1
if (-not $installer) {
    throw "No NSIS installer found under $NsisRoot"
}

if (-not (Test-Path $BuiltBackendExe -PathType Leaf)) {
    throw "Freshly built backend resource is missing at $BuiltBackendExe"
}

# Fail closed if unrelated processes already occupy certification ports.
foreach ($port in @(8765, $RetryBackendPort, $RetryMockPort)) {
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        throw "Port $port is already occupied before clean-install smoke certification."
    }
}

if (Test-Path $InstallDir) {
    Remove-Item -Recurse -Force $InstallDir
}
if (Test-Path $RetryConfigDir) {
    Remove-Item -Recurse -Force $RetryConfigDir
}
if (Test-Path $StateFile) {
    Remove-Item -Force $StateFile
}

Write-Host "[1/9] Installing NSIS bundle silently into isolated directory..." -ForegroundColor Yellow
# NSIS requires /D=<path> to be the final argument. GitHub runner TEMP paths do
# not contain spaces, so no installer-specific quoting workaround is required.
$install = Start-Process -FilePath $installer.FullName -ArgumentList @('/S', "/D=$InstallDir") -Wait -PassThru
if ($install.ExitCode -ne 0) {
    throw "NSIS silent install failed with exit code $($install.ExitCode)."
}
if (-not (Test-Path $InstallDir -PathType Container)) {
    throw "Installer exited successfully but did not create $InstallDir"
}

Write-Host "[2/9] Verifying packaged backend exists inside installed layout..." -ForegroundColor Yellow
$backendExe = Get-ChildItem -Path $InstallDir -Filter "ai-marketing-backend.exe" -File -Recurse -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $backendExe) {
    throw "Installed application does not contain ai-marketing-backend.exe."
}

Write-Host "[3/9] Verifying installed backend SHA-256 matches freshly built backend..." -ForegroundColor Yellow
$builtBackendHash = (Get-FileHash -Path $BuiltBackendExe -Algorithm SHA256).Hash.ToLowerInvariant()
$installedBackendHash = (Get-FileHash -Path $backendExe.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "      Built backend SHA-256:     $builtBackendHash" -ForegroundColor DarkGray
Write-Host "      Installed backend SHA-256: $installedBackendHash" -ForegroundColor DarkGray
if ($installedBackendHash -ne $builtBackendHash) {
    throw "Installed backend hash does not match the freshly built backend resource. built=$builtBackendHash installed=$installedBackendHash"
}
"$builtBackendHash  src-tauri/resources/backend/ai-marketing-backend.exe" |
    Set-Content -Path $BackendChecksumFile -Encoding utf8
Write-Host "INSTALLED_BACKEND_SHA256_MATCH_OK" -ForegroundColor Green

Write-Host "[4/9] Launching installed backend directly for isolated retry certification..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $RetryConfigDir | Out-Null
$retryProc = $null
try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $backendExe.FullName
    $psi.Arguments = "--emit-bootstrap --port $RetryBackendPort"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $false
    $psi.CreateNoWindow = $true
    $psi.EnvironmentVariables["AI_MARKETING_CONFIG_DIR"] = $RetryConfigDir
    $psi.EnvironmentVariables["AI_MARKETING_KNOWLEDGE_EPHEMERAL"] = "1"
    $psi.EnvironmentVariables["AI_MARKETING_MEMORY_EPHEMERAL"] = "1"
    $psi.EnvironmentVariables["AI_MARKETING_LEARNING_EPHEMERAL"] = "1"
    $retryProc = [System.Diagnostics.Process]::Start($psi)

    $bootstrapDeadline = [DateTime]::UtcNow.AddSeconds(30)
    $bootstrap = $null
    while ([DateTime]::UtcNow -lt $bootstrapDeadline -and -not $retryProc.HasExited) {
        if ($retryProc.StandardOutput.Peek() -ge 0) {
            $line = $retryProc.StandardOutput.ReadLine()
            if ($line -and $line.StartsWith("UIAUTH_BOOTSTRAP_V1:")) {
                $bootstrap = $line
                break
            }
        } else {
            Start-Sleep -Milliseconds 50
        }
    }
    if (-not $bootstrap) {
        throw "Installed backend did not emit a bootstrap frame for retry certification."
    }

    $bootstrapPayload = $bootstrap.Substring("UIAUTH_BOOTSTRAP_V1:".Length) | ConvertFrom-Json
    $retryToken = [string]$bootstrapPayload.token
    $retryHost = [string]$bootstrapPayload.host
    $retryPort = [int]$bootstrapPayload.port
    if ([string]::IsNullOrWhiteSpace($retryToken)) {
        throw "Installed backend retry bootstrap did not include an auth token."
    }
    if ($retryHost -ne "127.0.0.1" -or $retryPort -ne $RetryBackendPort) {
        throw "Installed backend retry bootstrap returned unexpected endpoint $retryHost`:$retryPort."
    }

    $retryBackendBaseUrl = "http://$retryHost`:$retryPort"
    $retryHealth = Invoke-RestMethod -Uri "$retryBackendBaseUrl/api/health" -Method Get -TimeoutSec 10
    if ($retryHealth.status -ne "ok") {
        throw "Installed backend retry probe health check failed."
    }

    Write-Host "[5/9] Proving installed backend retries a real HTTP 502 and recovers on HTTP 200..." -ForegroundColor Yellow
    & (Join-Path $Root "scripts\smoke_installed_transient_retry.ps1") `
        -BackendBaseUrl $retryBackendBaseUrl `
        -BearerToken $retryToken `
        -MockPort $RetryMockPort
} finally {
    if ($retryProc -and -not $retryProc.HasExited) {
        Stop-Process -Id $retryProc.Id -Force -ErrorAction SilentlyContinue
        try { $null = $retryProc.WaitForExit(5000) } catch {}
    }
    Remove-Item -Recurse -Force $RetryConfigDir -ErrorAction SilentlyContinue
}

Write-Host "[6/9] Locating installed desktop executable..." -ForegroundColor Yellow
$desktopExe = Get-ChildItem -Path $InstallDir -Filter "*.exe" -File -Recurse |
    Where-Object {
        $_.Name -ne "ai-marketing-backend.exe" -and
        $_.Name -notmatch "(?i)uninstall|unins" -and
        $_.FullName -notmatch "(?i)[\\/]resources[\\/]backend[\\/]"
    } |
    Sort-Object Length -Descending |
    Select-Object -First 1
if (-not $desktopExe) {
    throw "Could not locate the installed desktop executable."
}
Write-Host "      Desktop executable: $($desktopExe.FullName)"

Write-Host "[7/9] Launching installed desktop and waiting for packaged backend health..." -ForegroundColor Yellow
$desktop = Start-Process -FilePath $desktopExe.FullName -WorkingDirectory $desktopExe.DirectoryName -PassThru
$healthOk = $false
$healthDeadline = [DateTime]::UtcNow.AddSeconds(30)
while ([DateTime]::UtcNow -lt $healthDeadline) {
    if ($desktop.HasExited) {
        throw "Installed desktop exited before backend became healthy. ExitCode=$($desktop.ExitCode)"
    }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -Method Get -TimeoutSec 2
        if ($health.status -eq "ok" -and $health.service -eq "AI Marketing Department API") {
            $healthOk = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 250
    }
}
if (-not $healthOk) {
    throw "Installed application did not expose a healthy packaged backend within 30 seconds."
}
Write-Host "      Installed backend health OK" -ForegroundColor Green

Write-Host "[8/9] Capturing authoritative backend PID..." -ForegroundColor Yellow
$stateDeadline = [DateTime]::UtcNow.AddSeconds(10)
$backendPid = $null
while ([DateTime]::UtcNow -lt $stateDeadline) {
    if (Test-Path $StateFile) {
        try {
            $state = Get-Content -Raw $StateFile | ConvertFrom-Json
            if ($state.service -eq "AI Marketing Department API" -and [int]$state.pid -gt 0) {
                $backendPid = [int]$state.pid
                break
            }
        } catch {
            # The state file is written atomically; retry if antivirus/filesystem
            # timing briefly exposes the old path during replacement.
        }
    }
    Start-Sleep -Milliseconds 100
}
if (-not $backendPid) {
    throw "Healthy installed backend did not publish a valid runtime state/PID."
}
if (-not (Get-Process -Id $backendPid -ErrorAction SilentlyContinue)) {
    throw "Backend PID $backendPid from runtime state is not alive."
}

Write-Host "[9/9] Closing desktop and verifying Job Object tears down backend..." -ForegroundColor Yellow
Stop-Process -Id $desktop.Id -Force -ErrorAction Stop
try { Wait-Process -Id $desktop.Id -Timeout 10 -ErrorAction SilentlyContinue } catch {}

$teardownDeadline = [DateTime]::UtcNow.AddSeconds(15)
while ([DateTime]::UtcNow -lt $teardownDeadline) {
    if (-not (Get-Process -Id $backendPid -ErrorAction SilentlyContinue)) {
        Write-Host "      Backend teardown OK" -ForegroundColor Green
        break
    }
    Start-Sleep -Milliseconds 200
}
if (Get-Process -Id $backendPid -ErrorAction SilentlyContinue) {
    Stop-Process -Id $backendPid -Force -ErrorAction SilentlyContinue
    throw "Backend PID $backendPid survived desktop termination; Job Object cleanup failed."
}

# The runner is ephemeral, but remove the isolated install tree to prove no
# source checkout dependency is needed after the installed-app smoke run.
if (Test-Path $InstallDir) {
    Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
}

Write-Host "CLEAN_INSTALL_CERTIFICATION_OK" -ForegroundColor Green
