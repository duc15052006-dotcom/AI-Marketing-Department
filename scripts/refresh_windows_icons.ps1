Add-Type @"
using System;
using System.Runtime.InteropServices;

public class ShellNotifier {
    [DllImport("shell32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    public static extern void SHChangeNotify(int wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);

    public const int SHCNE_ASSOCCHANGED = 0x08000000;
    public const uint SHCNF_IDLIST = 0x0000;
    public const uint SHCNF_FLUSH = 0x1000;

    public static void NotifyShell() {
        SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST | SHCNF_FLUSH, IntPtr.Zero, IntPtr.Zero);
    }
}
"@

$userHome = $env:USERPROFILE
$publicHome = $env:PUBLIC

$desktopPaths = @(
    "$userHome\Desktop",
    "$userHome\OneDrive\Desktop",
    "$publicHome\Desktop"
)

$targetExe = "C:\AI-Marketing-Department\src-tauri\target\release\ai-marketing-department-desktop.exe"
$ws = New-Object -ComObject WScript.Shell

foreach ($d in $desktopPaths) {
    if (Test-Path $d) {
        Get-ChildItem -Path $d -Filter "*AI Marketing*" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $d -Filter "*ai-marketing-department-desktop*" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

        $newShortcutPath = Join-Path $d "AI Marketing Department.lnk"
        $sc = $ws.CreateShortcut($newShortcutPath)
        $sc.TargetPath = $targetExe
        $sc.WorkingDirectory = "C:\AI-Marketing-Department"
        $sc.IconLocation = "$targetExe,0"
        $sc.Description = "AI Marketing Department — Command Center"
        $sc.Save()
        Write-Host "Created fresh shortcut at: $newShortcutPath"
    }
}

# Notify Windows Explorer Shell to refresh icons
[ShellNotifier]::NotifyShell()
Write-Host "Windows Shell notified of icon changes (SHCNE_ASSOCCHANGED)."
