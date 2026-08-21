$conns = Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in $conns) {
        $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        Write-Host "PORT 8765: PID=$($c.OwningProcess) Name=$($p.ProcessName) Path=$($p.Path)"
    }
} else {
    Write-Host "PORT 8765 is NOT currently in use."
}
