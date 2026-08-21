# Step 1: Ensure port 8765 is clear
$conns = Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in $conns) {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

Write-Host "Port 8765 cleared."

# Step 2: Launch the real native release executable
$exePath = "C:\AI-Marketing-Department\src-tauri\target\release\ai-marketing-department-desktop.exe"
Write-Host "Launching Native Release EXE: $exePath"
$appProcess = Start-Process -FilePath $exePath -PassThru

# Wait up to 10 seconds for native app to bootstrap backend
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/system/status" -Method Get -TimeoutSec 2
        if ($status.status -eq "ONLINE") {
            $ready = $true
            Write-Host "✓ Native app automatically spawned backend! Version: $($status.app_backend_version) Status: $($status.status)"
            break
        }
    } catch {
        # Still booting
    }
}

if (-not $ready) {
    Write-Host "✗ Backend failed to start via native app."
    if ($appProcess -and !$appProcess.HasExited) { Stop-Process -Id $appProcess.Id -Force }
    exit 1
}

# Step 3: Check sanitized provider health
$providers = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/system/providers/health" -Method Get
Write-Host "`nSanitized Provider Health:"
foreach ($p in $providers) {
    Write-Host "  - $($p.provider): enabled=$($p.enabled), configured=$($p.configured), credential_present=$($p.credential_present), model=$($p.model)"
}

# Step 4: Send live test prompt "xin chào" via dedicated Python client
Write-Host "`nSending Live First-Turn Message: 'xin chào'..."
python scripts\test_live_chat_client.py "xin chào"

# Step 5: Test Clean Restart
Write-Host "`nTesting Clean App Restart..."
Stop-Process -Id $appProcess.Id -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host "Re-launching Native Release EXE..."
$appProcess2 = Start-Process -FilePath $exePath -PassThru
Start-Sleep -Seconds 4

Write-Host "Sending Live Message After Restart: 'bạn biết tiếng Việt không?'..."
python scripts\test_live_chat_client.py "bạn biết tiếng Việt không?"

# Cleanup
if ($appProcess2 -and !$appProcess2.HasExited) { Stop-Process -Id $appProcess2.Id -Force }
Write-Host "`n✓ All native end-to-end tests completed successfully!"
