# AI Marketing Department — Local Desktop Launcher (PROD-UIAUTH-01RRV)
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  AI MARKETING DEPARTMENT — DESKTOP LAUNCHER" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

function Parse-BootstrapLines {
    param(
        [string[]]$Lines
    )
    $bootstrapFrameCount = 0
    $token = ""
    $hostVal = "127.0.0.1"
    $portVal = 8765
    $duplicateDetected = $false
    $parseError = $false

    foreach ($line in $Lines) {
        if ($null -eq $line) { continue }
        $trimmed = $line.Trim()
        if ($trimmed.StartsWith("UIAUTH_BOOTSTRAP_V1:")) {
            $bootstrapFrameCount++
            if ($bootstrapFrameCount -gt 1) {
                $duplicateDetected = $true
                break
            }
            $jsonStr = $trimmed.Substring("UIAUTH_BOOTSTRAP_V1:".Length)
            try {
                $bootJson = $jsonStr | ConvertFrom-Json
                if ($bootJson.token -and $bootJson.token.Length -ge 32 -and $bootJson.token.Length -le 256) {
                    $token = $bootJson.token
                } else {
                    $parseError = $true
                }
                if ($bootJson.host -and ($bootJson.host -eq "127.0.0.1" -or $bootJson.host -eq "localhost" -or $bootJson.host -eq "::1")) {
                    $hostVal = $bootJson.host
                } else {
                    $parseError = $true
                }
                if ($bootJson.port -and [int]$bootJson.port -ge 1 -and [int]$bootJson.port -le 65535) {
                    $portVal = [int]$bootJson.port
                } else {
                    $parseError = $true
                }
            } catch {
                $parseError = $true
            }
        }
    }

    if ($duplicateDetected) {
        return @{ Success = $false; Error = "DUPLICATE_BOOTSTRAP_FRAME" }
    }
    if ($bootstrapFrameCount -eq 0) {
        return @{ Success = $false; Error = "NO_BOOTSTRAP_FRAME" }
    }
    if ($parseError -or -not $token) {
        return @{ Success = $false; Error = "INVALID_BOOTSTRAP_PAYLOAD" }
    }

    return @{
        Success = $true
        Token = $token
        Host = $hostVal
        Port = $portVal
    }
}

function Stop-ProcessTree {
    param(
        [int]$ParentId
    )
    if (-not $ParentId -or $ParentId -le 0) { return }

    # Double-pass descendant gathering and termination to eliminate descendant-spawn race
    for ($pass = 1; $pass -le 2; $pass++) {
        $descendants = @()
        $queue = [System.Collections.Generic.Queue[int]]::new()
        $queue.Enqueue($ParentId)

        while ($queue.Count -gt 0) {
            $curr = $queue.Dequeue()
            try {
                $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $curr" -ErrorAction SilentlyContinue
                if ($children) {
                    foreach ($c in $children) {
                        $cId = [int]$c.ProcessId
                        if ($cId -gt 0 -and $cId -notin $descendants -and $cId -ne $ParentId) {
                            $descendants += $cId
                            $queue.Enqueue($cId)
                        }
                    }
                }
            } catch {}
        }

        # Terminate descendants first (bottom-up)
        [array]::Reverse($descendants)
        foreach ($dId in $descendants) {
            try {
                Stop-Process -Id $dId -Force -ErrorAction SilentlyContinue
            } catch {}
        }

        # Terminate root parent process
        try {
            Stop-Process -Id $ParentId -Force -ErrorAction SilentlyContinue
        } catch {}

        if ($pass -eq 1) {
            Start-Sleep -Milliseconds 50
        }
    }
}

# 1. Start Python Localhost API with Secure Bootstrap Pipe
Write-Host "[1/3] Starting Python Localhost API with secure bootstrap..." -ForegroundColor Yellow

# Resolve real Python interpreter (PROD-DESKTOP-BOOTSTRAP-LAUNCHER-01).
# On Windows the bare "python" command may resolve to a 0-byte Windows Store
# App Execution Alias that spawns the real interpreter as a child, breaking
# stdout pipe ownership.  We resolve the actual executable before launching.
$resolvedPythonExe = $null

# A. Prefer project-local virtualenv if present
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $resolvedPythonExe = $venvPython
}

# B. Otherwise ask the existing "python" for its real executable path
if (-not $resolvedPythonExe) {
    try {
        $probe = & python -c "import sys; print(sys.executable)" 2>$null
        if ($probe -and (Test-Path -LiteralPath $probe.Trim())) {
            $resolvedPythonExe = $probe.Trim()
        }
    } catch {}
}

# C. Fallback: try the Python Launcher for Windows (py.exe)
if (-not $resolvedPythonExe) {
    try {
        $probe = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($probe -and (Test-Path -LiteralPath $probe.Trim())) {
            $resolvedPythonExe = $probe.Trim()
        }
    } catch {}
}

# D. Validate: reject WindowsApps alias and anything unusable
if (-not $resolvedPythonExe) {
    Write-Host "      ✗ Critical: PYTHON_INTERPRETER_NOT_FOUND — cannot locate a Python interpreter." -ForegroundColor Red
    exit 1
}
if ($resolvedPythonExe -match "WindowsApps") {
    Write-Host "      ✗ Critical: resolved Python is the Windows Store alias ($resolvedPythonExe), which cannot own stdout. Aborting." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath $resolvedPythonExe -PathType Leaf)) {
    Write-Host "      ✗ Critical: resolved Python path is not a file: $resolvedPythonExe" -ForegroundColor Red
    exit 1
}

Write-Host "      Using Python: $resolvedPythonExe" -ForegroundColor DarkGray

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $resolvedPythonExe
$psi.Arguments = "app_api/server.py --emit-bootstrap"
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true
$pythonProcess = [System.Diagnostics.Process]::Start($psi)

# Non-blocking bootstrap read (PROD-DESKTOP-BOOTSTRAP-READ-HANG-01).
# The server is long-lived so EndOfStream never becomes true.  We poll
# stdout with Peek()/Read() and stop as soon as a valid bootstrap frame
# arrives, with a hard deadline to prevent infinite hangs.  The ongoing
# stdout drain is handled by a background runspace after bootstrap.
$bootstrapLines = @()
$bootstrapFound = $false
$bootstrapTimeoutSec = 12
$lineBuf = ""

$sw = [System.Diagnostics.Stopwatch]::StartNew()
while ($sw.Elapsed.TotalSeconds -lt $bootstrapTimeoutSec) {
    if ($pythonProcess.HasExited) { break }
    while ($pythonProcess.StandardOutput.Peek() -ge 0) {
        $ch = [char]$pythonProcess.StandardOutput.Read()
        $lineBuf += $ch
        if ($ch -eq "`n") {
            $line = $lineBuf.TrimEnd("`r","`n")
            $bootstrapLines += $line
            $lineBuf = ""
            if ($line.Trim().StartsWith("UIAUTH_BOOTSTRAP_V1:")) {
                $bootstrapFound = $true
                break
            }
        }
    }
    if ($bootstrapFound) { break }
    Start-Sleep -Milliseconds 50
}
$sw.Stop()

$bootResult = Parse-BootstrapLines -Lines $bootstrapLines

if (-not $bootResult.Success) {
    $errLines = @()
    $errBuf = ""
    while ($pythonProcess.StandardError.Peek() -ge 0) {
        $ch = [char]$pythonProcess.StandardError.Read()
        $errBuf += $ch
        if ($ch -eq "`n") {
            $errLines += $errBuf.TrimEnd("`r","`n")
            $errBuf = ""
        }
    }
    $errDetail = ""
    if ($errLines.Count -gt 0) {
        $tail = $errLines | Select-Object -Last 5
        $errDetail = " | stderr: " + ($tail -join " ")
    }
    Write-Host "      ✗ Critical: Backend bootstrap handshake failed ($($bootResult.Error)$errDetail). Terminating." -ForegroundColor Red
    if ($pythonProcess -and !$pythonProcess.HasExited) { Stop-ProcessTree -ParentId $pythonProcess.Id }
    exit 1
}

# Background drain: keep stdout/stderr consumed to prevent pipe buffer deadlock.
$drainRunspace = [System.Management.Automation.Runspaces.RunspaceFactory]::CreateRunspace()
$drainRunspace.Open()
$drainPS = [System.Management.Automation.PowerShell]::Create()
$drainPS.Runspace = $drainRunspace
[void]$drainPS.AddScript({
    param($stdout, $stderr)
    try {
        while ($true) {
            if ($stdout.Peek() -ge 0) { $stdout.Read() | Out-Null } else { Start-Sleep -Milliseconds 100 }
            if ($stderr.Peek() -ge 0) { $stderr.Read() | Out-Null }
        }
    } catch {}
}).AddArgument($pythonProcess.StandardOutput).AddArgument($pythonProcess.StandardError)
$drainPS.BeginInvoke() | Out-Null

$sessionToken = $bootResult.Token
$apiHost = $bootResult.Host
$apiPort = $bootResult.Port

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

$npmCmd = (Get-Command "npm.cmd" -ErrorAction SilentlyContinue).Source
if (-not $npmCmd) { $npmCmd = "npm" }
$frontendProcess = Start-Process -FilePath $npmCmd -ArgumentList "--prefix frontend run dev" -PassThru -NoNewWindow

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
    Write-Host "`nStopping AI Marketing Department process trees..." -ForegroundColor Yellow
    if ($drainPS) { try { $drainPS.Stop(); $drainPS.Dispose() } catch {} }
    if ($drainRunspace) { try { $drainRunspace.Close(); $drainRunspace.Dispose() } catch {} }
    if ($pythonProcess -and !$pythonProcess.HasExited) { Stop-ProcessTree -ParentId $pythonProcess.Id }
    if ($frontendProcess -and !$frontendProcess.HasExited) { Stop-ProcessTree -ParentId $frontendProcess.Id }
    $env:APP_BACKEND_HOST_DEV = $null
    $env:APP_BACKEND_PORT_DEV = $null
    $env:APP_BACKEND_BEARER_DEV = $null
    $env:APP_BACKEND_TARGET = $null
    Write-Host "Shutdown complete. Process trees terminated." -ForegroundColor Green
}
