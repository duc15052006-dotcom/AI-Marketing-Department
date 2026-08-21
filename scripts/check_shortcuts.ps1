$userHome = $env:USERPROFILE
$publicHome = $env:PUBLIC

$paths = @(
    "$userHome\Desktop",
    "$userHome\OneDrive\Desktop",
    "$publicHome\Desktop"
)

foreach ($p in $paths) {
    if (Test-Path $p) {
        Write-Host "=== Checking $p ==="
        Get-ChildItem -Path $p -Filter "*.lnk" | ForEach-Object {
            $ws = New-Object -ComObject WScript.Shell
            $sc = $ws.CreateShortcut($_.FullName)
            Write-Host "Name: $($_.Name)"
            Write-Host "  Path: $($_.FullName)"
            Write-Host "  TargetPath: $($sc.TargetPath)"
            Write-Host "  IconLocation: $($sc.IconLocation)"
        }
    }
}
