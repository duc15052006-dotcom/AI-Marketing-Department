$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDist = Join-Path $Root "build\backend-dist"
$BackendWork = Join-Path $Root "build\backend-work"
$BackendResourceDir = Join-Path $Root "src-tauri\resources\backend"
$BackendExe = Join-Path $BackendDist "ai-marketing-backend.exe"
$BackendResourceExe = Join-Path $BackendResourceDir "ai-marketing-backend.exe"

Write-Host "== AI Marketing Department v1 Windows release build ==" -ForegroundColor Cyan
Write-Host "Root: $Root"

Push-Location $Root
try {
    New-Item -ItemType Directory -Force -Path $BackendDist, $BackendWork, $BackendResourceDir | Out-Null
    if (Test-Path $BackendResourceExe) { Remove-Item -Force $BackendResourceExe }

    Write-Host "[1/7] Installing Python runtime/build dependencies..." -ForegroundColor Yellow
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    python -m pip install "pyinstaller==6.22.3"

    Write-Host "[2/7] Running deterministic Python productization tests..." -ForegroundColor Yellow
    python -m unittest tests.test_release_productization_v1 -v
    Write-Host "      Running real-HTTP transient retry regression..." -ForegroundColor DarkGray
    python -m unittest tests.test_openai_compatible_real_http_retry_v1 -v

    Write-Host "[3/7] Building standalone backend sidecar..." -ForegroundColor Yellow
    python -m PyInstaller --noconfirm --clean --distpath $BackendDist --workpath $BackendWork packaging/backend.spec
    if (-not (Test-Path $BackendExe -PathType Leaf)) {
        throw "Standalone backend was not produced at $BackendExe"
    }
    Copy-Item -Force $BackendExe $BackendResourceExe

    Write-Host "[4/7] Smoke-testing standalone backend bootstrap, health, model connection, and full workflow..." -ForegroundColor Yellow
    $releaseSmokeConfig = Join-Path $Root "build\release-smoke-config"
    if (Test-Path $releaseSmokeConfig) {
        Remove-Item -Recurse -Force $releaseSmokeConfig
    }
    New-Item -ItemType Directory -Force -Path $releaseSmokeConfig | Out-Null

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $BackendResourceExe
    $psi.Arguments = "--emit-bootstrap --port 18765"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    # Keep stderr attached to the CI console. This both exposes safe runtime
    # diagnostics and prevents an undrained redirected stderr pipe from
    # backpressuring the packaged backend during the full-workflow smoke.
    $psi.RedirectStandardError = $false
    $psi.CreateNoWindow = $true
    $psi.EnvironmentVariables["AI_MARKETING_CONFIG_DIR"] = $releaseSmokeConfig
    $proc = [System.Diagnostics.Process]::Start($psi)
    try {
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        $bootstrap = $null
        while ([DateTime]::UtcNow -lt $deadline -and -not $proc.HasExited) {
            if ($proc.StandardOutput.Peek() -ge 0) {
                $line = $proc.StandardOutput.ReadLine()
                if ($line -and $line.StartsWith("UIAUTH_BOOTSTRAP_V1:")) {
                    $bootstrap = $line
                    break
                }
            } else {
                Start-Sleep -Milliseconds 50
            }
        }
        if (-not $bootstrap) {
            throw "Standalone backend did not emit a bootstrap frame. Backend stderr is emitted directly to the CI console above."
        }

        $bootstrapJson = $bootstrap.Substring("UIAUTH_BOOTSTRAP_V1:".Length)
        $bootstrapPayload = $bootstrapJson | ConvertFrom-Json
        $bootstrapToken = [string]$bootstrapPayload.token
        $bootstrapHost = [string]$bootstrapPayload.host
        $bootstrapPort = [int]$bootstrapPayload.port
        if ([string]::IsNullOrWhiteSpace($bootstrapToken)) {
            throw "Standalone backend bootstrap frame did not include an auth token."
        }
        if ($bootstrapHost -ne "127.0.0.1") {
            throw "Standalone backend bootstrap returned unexpected host '$bootstrapHost'."
        }
        if ($bootstrapPort -ne 18765) {
            throw "Standalone backend bootstrap returned unexpected port '$bootstrapPort'."
        }

        $backendBaseUrl = "http://$bootstrapHost`:$bootstrapPort"
        $health = Invoke-RestMethod -Uri "$backendBaseUrl/api/health" -Method Get -TimeoutSec 10
        if ($health.status -ne "ok") {
            throw "Standalone backend health endpoint returned unexpected status: $($health.status)"
        }
        Write-Host "      Backend bootstrap + health OK" -ForegroundColor Green

        & (Join-Path $Root "scripts\smoke_packaged_model_connection.ps1") -BackendBaseUrl $backendBaseUrl -BearerToken $bootstrapToken
        & (Join-Path $Root "scripts\smoke_packaged_full_workflow.ps1") -BackendBaseUrl $backendBaseUrl -BearerToken $bootstrapToken
    } finally {
        if (-not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            $null = $proc.WaitForExit(5000)
        }
        Remove-Item -Recurse -Force $releaseSmokeConfig -ErrorAction SilentlyContinue
    }

    Write-Host "[5/7] Installing and testing frontend..." -ForegroundColor Yellow
    npm --prefix frontend ci
    npm --prefix frontend test
    npm --prefix frontend run build

    Write-Host "[6/7] Running Rust desktop tests..." -ForegroundColor Yellow
    cargo test --manifest-path src-tauri/Cargo.toml

    Write-Host "[7/7] Building Windows MSI/NSIS bundles..." -ForegroundColor Yellow
    # Run from repository root so Tauri resolves ./src-tauri deterministically.
    npx --yes "@tauri-apps/cli@2.11.4" build

    $BundleRoot = Join-Path $Root "src-tauri\target\release\bundle"
    if (-not (Test-Path $BundleRoot -PathType Container)) {
        throw "Tauri bundle directory was not produced at $BundleRoot"
    }

    $installers = Get-ChildItem -Path $BundleRoot -Recurse -File | Where-Object { $_.Extension -in @('.msi', '.exe') }
    if (-not $installers -or $installers.Count -lt 1) {
        throw "No Windows installer (.msi/.exe) was produced under $BundleRoot"
    }

    Write-Host "Release build completed." -ForegroundColor Green
    Write-Host "Bundles: $BundleRoot"
} finally {
    Pop-Location
}
