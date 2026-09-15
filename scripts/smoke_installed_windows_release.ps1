$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BundleRoot = Join-Path $Root "src-tauri\target\release\bundle"
$NsisRoot = Join-Path $BundleRoot "nsis"
$RunSuffix = if ($env:GITHUB_RUN_ID) { $env:GITHUB_RUN_ID } else { [Guid]::NewGuid().ToString("N") }
$InstallDir = Join-Path $env:TEMP "ai-marketing-department-clean-install-$RunSuffix"
$RuntimeDir = Join-Path $env:APPDATA "AI-Marketing-Department\runtime"
$StateFile = Join-Path $RuntimeDir "backend_instance.json"

Write-Host "== Clean-install Windows release certification ==" -ForegroundColor Cyan

$installer = Get-ChildItem -Path $NsisRoot -Filter "*.exe" -File -ErrorAction Stop |
    Sort-Object Length -Descending |
    Select-Object -First 1
if (-not $installer) {
    throw "No NSIS installer found under $NsisRoot"
}

# Fail closed if an unrelated process is already listening on the canonical port.
$listeners = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    throw "Port 8765 is already occupied before clean-install smoke certification."
}

if (Test-Path $InstallDir) {
    Remove-Item -Recurse -Force $InstallDir
}
if (Test-Path $StateFile) {
    Remove-Item -Force $StateFile
}

Write-Host "[1/6] Installing NSIS bundle silently into isolated directory..." -ForegroundColor Yellow
# NSIS requires /D=<path> to be the final argument. GitHub runner TEMP paths do
# not contain spaces, so no installer-specific quoting workaround is required.
$install = Start-Process -FilePath $installer.FullName -ArgumentList @('/S', "/D=$InstallDir") -Wait -PassThru
if ($install.ExitCode -ne 0) {
    throw "NSIS silent install failed with exit code $($install.ExitCode)."
}
if (-not (Test-Path $InstallDir -PathType Container)) {
    throw "Installer exited successfully but did not create $InstallDir"
}

Write-Host "[2/6] Verifying packaged backend exists inside installed layout..." -ForegroundColor Yellow
$backendExe = Get-ChildItem -Path $InstallDir -Filter "ai-marketing-backend.exe" -File -Recurse -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $backendExe) {
    throw "Installed application does not contain ai-marketing-backend.exe."
}

Write-Host "[3/6] Locating installed desktop executable..." -ForegroundColor Yellow
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

Write-Host "[4/6] Launching installed desktop and waiting for packaged backend health..." -ForegroundColor Yellow
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

Write-Host "[5/6] Capturing authoritative backend PID..." -ForegroundColor Yellow
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

Write-Host "[6/6] Closing desktop and verifying Job Object tears down backend..." -ForegroundColor Yellow
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
