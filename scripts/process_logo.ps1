Add-Type -AssemblyName System.Drawing

$srcPath = "C:\Users\DUCK\.gemini\antigravity\brain\542b53ed-5091-4842-98c1-78dec634678a\.user_uploaded\media_1787177067791.png"
$brandDir = "frontend\src\assets\brand"
New-Item -ItemType Directory -Force -Path $brandDir | Out-Null
Copy-Item $srcPath (Join-Path $brandDir "logo-original.png") -Force

$bmp = [System.Drawing.Bitmap]::FromFile($srcPath)
$width = $bmp.Width
$height = $bmp.Height

$outBmp = New-Object System.Drawing.Bitmap($width, $height, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)

for ($y = 0; $y -lt $height; $y++) {
    for ($x = 0; $x -lt $width; $x++) {
        $c = $bmp.GetPixel($x, $y)
        $lum = [int](0.299 * $c.R + 0.587 * $c.G + 0.114 * $c.B)
        if ($lum -lt 30) {
            $outBmp.SetPixel($x, $y, [System.Drawing.Color]::FromArgb(0, 0, 0, 0))
        } elseif ($lum -gt 150) {
            $outBmp.SetPixel($x, $y, [System.Drawing.Color]::FromArgb(255, 236, 236, 236))
        } else {
            $alpha = [int]((($lum - 30.0) / (150.0 - 30.0)) * 255.0)
            if ($alpha -lt 0) { $alpha = 0 }
            if ($alpha -gt 255) { $alpha = 255 }
            $outBmp.SetPixel($x, $y, [System.Drawing.Color]::FromArgb($alpha, 236, 236, 236))
        }
    }
}
$bmp.Dispose()

$transparentPath = Join-Path $brandDir "logo-light-transparent.png"
$outBmp.Save($transparentPath, [System.Drawing.Imaging.ImageFormat]::Png)
$outBmp.Save("frontend\src\assets\logo.png", [System.Drawing.Imaging.ImageFormat]::Png)
$outBmp.Save("frontend\public\logo.png", [System.Drawing.Imaging.ImageFormat]::Png)
$outBmp.Save("frontend\public\favicon.png", [System.Drawing.Imaging.ImageFormat]::Png)

# Resize for Tauri icons
$iconsDir = "src-tauri\icons"
New-Item -ItemType Directory -Force -Path $iconsDir | Out-Null

function Resize-Image($img, $w, $h, $dest) {
    $resized = New-Object System.Drawing.Bitmap($w, $h, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($resized)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.Clear([System.Drawing.Color]::Transparent)
    $g.DrawImage($img, 0, 0, $w, $h)
    $g.Dispose()
    $resized.Save($dest, [System.Drawing.Imaging.ImageFormat]::Png)
    $resized.Dispose()
}

Resize-Image $outBmp 32 32 (Join-Path $iconsDir "32x32.png")
Resize-Image $outBmp 128 128 (Join-Path $iconsDir "128x128.png")
Resize-Image $outBmp 128 128 (Join-Path $iconsDir "icon.png")

# Save ICO
$ico32 = New-Object System.Drawing.Bitmap(32, 32, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($ico32)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.DrawImage($outBmp, 0, 0, 32, 32)
$g.Dispose()
$hIcon = $ico32.GetHicon()
$icon = [System.Drawing.Icon]::FromHandle($hIcon)
$fs = New-Object System.IO.FileStream((Join-Path $iconsDir "icon.ico"), [System.IO.FileMode]::Create)
$icon.Save($fs)
$fs.Close()
$ico32.Dispose()

$outBmp.Dispose()
Write-Output "TRANSPARENT_LOGOS_AND_ICONS_SAVED_SUCCESSFULLY"
