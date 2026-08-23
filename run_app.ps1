# AI Marketing Department — Local Desktop Launcher (PROD-UIAUTH-01R)
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  AI MARKETING DEPARTMENT — DESKTOP LAUNCHER" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Start Python Localhost API with Secure Bootstrap Pipe
Write-Host "[1/3] Starting Python Localhost API with secure bootstrap..." -ForegroundColor Yellow

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "python"
$psi.Arguments = "app_api/server.py --emit-bootstrap"
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.CreateNoWindow = $true
$pythonProcess = [System.Diagnostics.Process]::Start($psi)

$bootstrapRaw = $pythonProcess.StandardOutput.ReadLine()
$sessionToken = ""
$apiHost = "127.0.0.1"
$apiPort = 8765

if ($bootstrapRaw -and $bootstrapRaw.StartsWith("UIAUTH_BOOTSTRAP_V1:")) {
    $jsonStr = $bootstrapRaw.Substring("UIAUTH_BOOTSTRAP_V1:".Length)
    try {
        $bootJson = $jsonStr | ConvertFrom-Json
        if ($bootJson.token -and $bootJson.token.Length -ge 32) {
            $sessionToken = $bootJson.token
        }
        if ($bootJson.host -and ($bootJson.host -eq "127.0.0.1" -or $bootJson.host -eq "localhost" -or $bootJson.host -eq "::1")) {
            $apiHost = $bootJson.host
        }
        if ($bootJson.port -and [int]$bootJson.port -ge 1 -and [int]$bootJson.port -le 65535) {
            $apiPort = [int]$bootJson.port
        }
    } catch {
        Write-Host "      ✗ Failed to parse bootstrap payload." -ForegroundColor Red
    }
}

if (-not $sessionToken) {
    Write-Host "      ✗ Critical: No valid runtime session token obtained from backend bootstrap." -ForegroundColor Red
}

Start-Sleep -Seconds 1

# 2. Check API Health (Public minimal endpoint)
try {
    $health = Invoke-RestMethod -Uri "http://${apiHost}:${apiPort}/api/health" -Method Get
    Write-Host "      ✓ API Connected and Ready on ${apiHost}:${apiPort} (Status: $($health.status))" -ForegroundColor Green
} catch {
    Write-Host "      ✗ Failed to connect to API on http://${apiHost}:${apiPort}" -ForegroundColor Red
}

# 3. Launch React / Vite Desktop Server with Authenticated Dev Proxy
Write-Host "[2/3] Starting React / Vite Dev Server with authenticated proxy..." -ForegroundColor Yellow
$env:APP_BACKEND_HOST_DEV = $apiHost
$env:APP_BACKEND_PORT_DEV = "$apiPort"
$env:APP_BACKEND_BEARER_DEV = $sessionToken
$env:APP_BACKEND_TARGET = "http://${apiHost}:${apiPort}"

$frontendProcess = Start-Process -FilePath "npm" -ArgumentList "--prefix frontend run dev" -PassThru -NoNewWindow

# Clean bearer token from parent PowerShell process environment
$env:APP_BACKEND_BEARER_DEV = $null

Start-Sleep -Seconds 3

# 4. Open Local Desktop Window
Write-Host "[3/3] Opening AI Marketing Department Command Center..." -ForegroundColor Green
Start-Process "http://localhost:3000"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  AI MARKETING DEPARTMENT IS RUNNING" -ForegroundColor Green
Write-Host "  Press Ctrl+C to shutdown all servers." -ForegroundColor Gray
Write-Host "==================================================" -ForegroundColor Cyan

try {
    while ($true) {
        Start-Sleep -Seconds 1
    }
} finally {
    Write-Host "`nStopping AI Marketing Department processes..." -ForegroundColor Yellow
    if ($pythonProcess -and !$pythonProcess.HasExited) { Stop-Process -Id $pythonProcess.Id -Force }
    if ($frontendProcess -and !$frontendProcess.HasExited) { Stop-Process -Id $frontendProcess.Id -Force }
    $env:APP_BACKEND_HOST_DEV = $null
    $env:APP_BACKEND_PORT_DEV = $null
    $env:APP_BACKEND_BEARER_DEV = $null
    $env:APP_BACKEND_TARGET = $null
    Write-Host "Shutdown complete." -ForegroundColor Green
}
