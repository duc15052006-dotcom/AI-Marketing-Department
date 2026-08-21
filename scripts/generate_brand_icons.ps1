Add-Type -AssemblyName System.Drawing

$sourcePath = "C:\Users\DUCK\.gemini\antigravity\brain\542b53ed-5091-4842-98c1-78dec634678a\.user_uploaded\media_1787179162607.png"
$brandDir = "c:\AI-Marketing-Department\frontend\src\assets\brand"
$assetsDir = "c:\AI-Marketing-Department\frontend\src\assets"
$iconsDir = "c:\AI-Marketing-Department\src-tauri\icons"

if (-not (Test-Path $brandDir)) {
    New-Item -ItemType Directory -Path $brandDir -Force | Out-Null
}

$rawBitmap = [System.Drawing.Bitmap]::FromFile($sourcePath)
$width = $rawBitmap.Width
$height = $rawBitmap.Height

Write-Host "Source image dimensions: $width x $height"

# 1. Process alpha transparency based on luminance
$transparentBitmap = New-Object System.Drawing.Bitmap($width, $height, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)

# Find bounding box
$minX = $width; $maxX = 0; $minY = $height; $maxY = 0

for ($y = 0; $y -lt $height; $y++) {
    for ($x = 0; $x -lt $width; $x++) {
        $pixel = $rawBitmap.GetPixel($x, $y)
        $lum = [Math]::Max($pixel.R, [Math]::Max($pixel.G, $pixel.B))
        if ($lum -gt 25) {
            $alpha = [Math]::Min(255, [int]($lum * 1.05))
            $color = [System.Drawing.Color]::FromArgb($alpha, 255, 255, 255)
            $transparentBitmap.SetPixel($x, $y, $color)

            if ($x -lt $minX) { $minX = $x }
            if ($x -gt $maxX) { $maxX = $x }
            if ($y -lt $minY) { $minY = $y }
            if ($y -gt $maxY) { $maxY = $y }
        } else {
            $transparentBitmap.SetPixel($x, $y, [System.Drawing.Color]::FromArgb(0, 0, 0, 0))
        }
    }
}

$rawBitmap.Dispose()

$symWidth = $maxX - $minX + 1
$symHeight = $maxY - $minY + 1
Write-Host "Symbol Size: $symWidth x $symHeight"

# 2. Render onto square canvas with 10% balanced padding
$canvasSize = 1024
$masterBitmap = New-Object System.Drawing.Bitmap($canvasSize, $canvasSize, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($masterBitmap)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
$g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
$g.Clear([System.Drawing.Color]::Transparent)

$targetPadding = [int]($canvasSize * 0.10)
$targetAvailableSize = $canvasSize - ($targetPadding * 2)

$scale = [Math]::Min($targetAvailableSize / $symWidth, $targetAvailableSize / $symHeight)
$drawW = [int]($symWidth * $scale)
$drawH = [int]($symHeight * $scale)
$destX = [int](($canvasSize - $drawW) / 2)
$destY = [int](($canvasSize - $drawH) / 2)

$srcRect = New-Object System.Drawing.Rectangle($minX, $minY, $symWidth, $symHeight)
$destRect = New-Object System.Drawing.Rectangle($destX, $destY, $drawW, $drawH)

$g.DrawImage($transparentBitmap, $destRect, $srcRect, [System.Drawing.GraphicsUnit]::Pixel)
$g.Dispose()
$transparentBitmap.Dispose()

# Save master PNG
$masterPath = Join-Path $brandDir "app-icon-transparent.png"
$masterBitmap.Save($masterPath, [System.Drawing.Imaging.ImageFormat]::Png)
Write-Host "Saved master transparent icon: $masterPath"

# Save frontend logo.png
$frontendLogoPath = Join-Path $assetsDir "logo.png"
$masterBitmap.Save($frontendLogoPath, [System.Drawing.Imaging.ImageFormat]::Png)
Write-Host "Saved frontend logo: $frontendLogoPath"

# Helper function to resize and save PNG
function Save-ResizedPng($srcBmp, $outPath, $sz) {
    $resized = New-Object System.Drawing.Bitmap($sz, $sz, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $gr = [System.Drawing.Graphics]::FromImage($resized)
    $gr.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $gr.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $gr.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $gr.Clear([System.Drawing.Color]::Transparent)
    $gr.DrawImage($srcBmp, 0, 0, $sz, $sz)
    $gr.Dispose()
    $resized.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $resized.Dispose()
}

$sizes = @(16, 24, 32, 48, 64, 128, 256, 512)
foreach ($s in $sizes) {
    Save-ResizedPng $masterBitmap (Join-Path $iconsDir "$s`x$s.png") $s
}
Save-ResizedPng $masterBitmap (Join-Path $iconsDir "icon.png") 512
Save-ResizedPng $masterBitmap (Join-Path $iconsDir "32x32@2x.png") 64
Save-ResizedPng $masterBitmap (Join-Path $iconsDir "128x128@2x.png") 256

# Windows specific tile icons
$tileSizes = @{
    "Square30x30Logo.png" = 30
    "Square44x44Logo.png" = 44
    "Square71x71Logo.png" = 71
    "Square89x89Logo.png" = 89
    "Square107x107Logo.png" = 107
    "Square142x142Logo.png" = 142
    "Square150x150Logo.png" = 150
    "Square284x284Logo.png" = 284
    "Square310x310Logo.png" = 310
    "StoreLogo.png" = 50
}
foreach ($kv in $tileSizes.GetEnumerator()) {
    Save-ResizedPng $masterBitmap (Join-Path $iconsDir $kv.Key) $kv.Value
}

# Function to build uncompressed 32bpp DIB for Windows ICO format
function Get-BmpDibBytes($srcBmp, $sz) {
    $resized = New-Object System.Drawing.Bitmap($sz, $sz, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $gr = [System.Drawing.Graphics]::FromImage($resized)
    $gr.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $gr.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $gr.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $gr.Clear([System.Drawing.Color]::Transparent)
    $gr.DrawImage($srcBmp, 0, 0, $sz, $sz)
    $gr.Dispose()

    $ms = New-Object System.IO.MemoryStream
    $bw = New-Object System.IO.BinaryWriter($ms)

    # BITMAPINFOHEADER (40 bytes)
    $bw.Write([UInt32]40)              # biSize
    $bw.Write([Int32]$sz)              # biWidth
    $bw.Write([Int32]($sz * 2))        # biHeight (XOR height + AND height)
    $bw.Write([UInt16]1)               # biPlanes
    $bw.Write([UInt16]32)              # biBitCount
    $bw.Write([UInt32]0)               # biCompression = BI_RGB
    $bw.Write([UInt32]($sz * $sz * 4)) # biSizeImage
    $bw.Write([Int32]0)                # biXPelsPerMeter
    $bw.Write([Int32]0)                # biYPelsPerMeter
    $bw.Write([UInt32]0)               # biClrUsed
    $bw.Write([UInt32]0)               # biClrImportant

    # XOR mask: BGRA bottom-up
    for ($y = $sz - 1; $y -ge 0; $y--) {
        for ($x = 0; $x -lt $sz; $x++) {
            $p = $resized.GetPixel($x, $y)
            $bw.Write([byte]$p.B)
            $bw.Write([byte]$p.G)
            $bw.Write([byte]$p.R)
            $bw.Write([byte]$p.A)
        }
    }

    # AND mask: 1-bit per pixel, DWORD-aligned rows (all 0 for 32bpp alpha)
    $rowBytes = [int]([Math]::Ceiling($sz / 32.0) * 4)
    $andRow = New-Object byte[] $rowBytes
    for ($y = 0; $y -lt $sz; $y++) {
        $bw.Write($andRow)
    }

    $resized.Dispose()
    $bw.Flush()
    $dibBytes = $ms.ToArray()
    $bw.Close()
    $ms.Dispose()

    return $dibBytes
}

# Function to get PNG bytes for 256x256
function Get-PngBytes($srcBmp, $sz) {
    $resized = New-Object System.Drawing.Bitmap($sz, $sz, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $gr = [System.Drawing.Graphics]::FromImage($resized)
    $gr.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $gr.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $gr.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $gr.Clear([System.Drawing.Color]::Transparent)
    $gr.DrawImage($srcBmp, 0, 0, $sz, $sz)
    $gr.Dispose()

    $ms = New-Object System.IO.MemoryStream
    $resized.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $bytes = $ms.ToArray()
    $ms.Dispose()
    $resized.Dispose()
    return $bytes
}

# Build multi-resolution ICO with native DIB frames for 16, 24, 32, 48, 64, 128 and PNG for 256
$icoEntries = @()
$dibSizes = @(16, 24, 32, 48, 64, 128)
foreach ($s in $dibSizes) {
    $bytes = Get-BmpDibBytes $masterBitmap $s
    $icoEntries += ,@($s, $bytes)
}

# 256x256 PNG frame
$png256Bytes = Get-PngBytes $masterBitmap 256
$icoEntries += ,@(256, $png256Bytes)

$masterBitmap.Dispose()

# Save icon.ico
$icoPath = Join-Path $iconsDir "icon.ico"
$fs = [System.IO.File]::Create($icoPath)
$bw = New-Object System.IO.BinaryWriter($fs)

# ICONDIR
$bw.Write([UInt16]0)
$bw.Write([UInt16]1)
$bw.Write([UInt16]$icoEntries.Count)

$offset = 6 + ($icoEntries.Count * 16)

foreach ($entry in $icoEntries) {
    $sz = $entry[0]
    $bytes = $entry[1]

    $wByte = if ($sz -ge 256) { [byte]0 } else { [byte]$sz }
    $hByte = if ($sz -ge 256) { [byte]0 } else { [byte]$sz }

    $bw.Write($wByte)
    $bw.Write($hByte)
    $bw.Write([byte]0)
    $bw.Write([byte]0)
    $bw.Write([UInt16]1)
    $bw.Write([UInt16]32)
    $bw.Write([UInt32]$bytes.Length)
    $bw.Write([UInt32]$offset)

    $offset += $bytes.Length
}

foreach ($entry in $icoEntries) {
    $bw.Write($entry[1])
}

$bw.Close()
$fs.Close()

Write-Host "Generated native Windows GDI-compliant icon.ico with $($icoEntries.Count) frames at $icoPath"
