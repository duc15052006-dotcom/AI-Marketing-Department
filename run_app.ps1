# AI Marketing Department — Local Desktop Launcher
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  AI MARKETING DEPARTMENT — DESKTOP LAUNCHER" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Start Python Localhost API in Background
Write-Host "[1/3] Starting Python Localhost API (127.0.0.1:8765)..." -ForegroundColor Yellow
$pythonProcess = Start-Process -FilePath "python" -ArgumentList "app_api/server.py" -PassThru -NoNewWindow

Start-Sleep -Seconds 2

# 2. Check API Health
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/system/status" -Method Get
    Write-Host "      ✓ API Connected: $($health.app_name) v$($health.version) [$($health.brain_version)]" -ForegroundColor Green
} catch {
    Write-Host "      ✗ Failed to connect to API on http://127.0.0.1:8765" -ForegroundColor Red
}

# 3. Launch Frontend / Desktop Window
Write-Host "[2/3] Starting React / Vite Desktop Server..." -ForegroundColor Yellow
$frontendProcess = Start-Process -FilePath "npm" -ArgumentList "--prefix frontend run dev" -PassThru -NoNewWindow

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
    Write-Host "Shutdown complete." -ForegroundColor Green
}
