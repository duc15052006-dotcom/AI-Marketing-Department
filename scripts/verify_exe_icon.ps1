Add-Type -AssemblyName System.Drawing

$exePath = "C:\AI-Marketing-Department\src-tauri\target\release\ai-marketing-department-desktop.exe"
$outExtractedPng = "C:\AI-Marketing-Department\scripts\extracted_exe_icon.png"

if (Test-Path $exePath) {
    $icon = [System.Drawing.Icon]::ExtractAssociatedIcon($exePath)
    $bmp = $icon.ToBitmap()
    $bmp.Save($outExtractedPng, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Host "Extracted icon size: $($bmp.Width) x $($bmp.Height)"
    
    # Check if there is any cyan/blue in the icon
    $hasCyan = $false
    $hasWhite = $false
    for ($y = 0; $y -lt $bmp.Height; $y++) {
        for ($x = 0; $x -lt $bmp.Width; $x++) {
            $p = $bmp.GetPixel($x, $y)
            # Cyan is typically high G and high B with low R
            if ($p.B -gt 150 -and $p.G -gt 150 -and $p.R -lt 50) {
                $hasCyan = $true
            }
            if ($p.R -gt 200 -and $p.G -gt 200 -and $p.B -gt 200) {
                $hasWhite = $true
            }
        }
    }
    Write-Host "Has Cyan pixels: $hasCyan"
    Write-Host "Has White logo pixels: $hasWhite"
    $bmp.Dispose()
    $icon.Dispose()
}
