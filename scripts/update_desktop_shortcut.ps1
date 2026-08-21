$desktopPath = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop)
$shortcutPath = Join-Path $desktopPath "AI Marketing Department.lnk"
$targetExe = "C:\AI-Marketing-Department\src-tauri\target\release\ai-marketing-department-desktop.exe"
$icoPath = "C:\AI-Marketing-Department\src-tauri\icons\icon.ico"

if (Test-Path $targetExe) {
    $ws = New-Object -ComObject WScript.Shell
    $shortcut = $ws.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $targetExe
    $shortcut.WorkingDirectory = "C:\AI-Marketing-Department"
    $shortcut.IconLocation = "$icoPath,0"
    $shortcut.Description = "AI Marketing Department — Command Center"
    $shortcut.Save()
    Write-Host "Created/updated desktop shortcut at: $shortcutPath"
}
