Add-Type -AssemblyName System.Drawing

$sourcePath = "c:\AI-Marketing-Department\frontend\src\assets\brand\app-icon-transparent.png"
$masterBitmap = [System.Drawing.Bitmap]::FromFile($sourcePath)

$iconsDir = "c:\AI-Marketing-Department\src-tauri\icons"
$icoPath = Join-Path $iconsDir "icon.ico"

# Create ICO with standard PNG frames (which rc.exe supports in modern Win10 SDK)
$icoSizes = @(16, 24, 32, 48, 64, 128, 256)
$pngFrames = @()

foreach ($sz in $icoSizes) {
    $resized = New-Object System.Drawing.Bitmap($sz, $sz, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $gr = [System.Drawing.Graphics]::FromImage($resized)
    $gr.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $gr.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $gr.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $gr.Clear([System.Drawing.Color]::Transparent)
    $gr.DrawImage($masterBitmap, 0, 0, $sz, $sz)
    $gr.Dispose()

    $ms = New-Object System.IO.MemoryStream
    $resized.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $bytes = $ms.ToArray()
    $ms.Dispose()
    $resized.Dispose()

    $pngFrames += ,@($sz, $bytes)
}

$masterBitmap.Dispose()

# Save ICO
$fs = [System.IO.File]::Create($icoPath)
$bw = New-Object System.IO.BinaryWriter($fs)

$bw.Write([UInt16]0) # Reserved
$bw.Write([UInt16]1) # Type = 1 (ICO)
$bw.Write([UInt16]$pngFrames.Count)

$offset = 6 + ($pngFrames.Count * 16)

foreach ($item in $pngFrames) {
    $sz = $item[0]
    $bytes = $item[1]

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

foreach ($item in $pngFrames) {
    $bw.Write($item[1])
}

$bw.Close()
$fs.Close()

Write-Host "Wrote PNG-based multi-frame ICO ($($pngFrames.Count) frames) to $icoPath"
