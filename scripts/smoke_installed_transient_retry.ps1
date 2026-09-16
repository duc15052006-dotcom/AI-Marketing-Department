param(
    [Parameter(Mandatory = $true)]
    [string]$BackendBaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$BearerToken,

    [int]$MockPort = 18770
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($BearerToken)) {
    throw "Installed transient-retry smoke requires a non-empty backend bearer token."
}
if ($MockPort -lt 1 -or $MockPort -gt 65535) {
    throw "MockPort must be between 1 and 65535."
}

$backend = $BackendBaseUrl.TrimEnd('/')
$existingListeners = @(Get-NetTCPConnection -LocalPort $MockPort -State Listen -ErrorAction SilentlyContinue)
if ($existingListeners.Count -gt 0) {
    throw "Retry mock provider port $MockPort is already occupied."
}

$countFile = Join-Path ([System.IO.Path]::GetTempPath()) ("ai-marketing-installed-retry-count-{0}.txt" -f ([Guid]::NewGuid().ToString("N")))
[System.IO.File]::WriteAllText($countFile, "0", [System.Text.Encoding]::ASCII)

Write-Host "== Installed backend transient retry smoke ==" -ForegroundColor Cyan
Write-Host "Injecting one real HTTP 502, then a valid HTTP 200 on loopback."

$mockJob = Start-Job -ArgumentList $MockPort, $countFile -ScriptBlock {
    param([int]$Port, [string]$CountFile)

    $ErrorActionPreference = "Stop"
    Set-StrictMode -Version Latest

    function Read-HttpRequest {
        param([System.Net.Sockets.NetworkStream]$Stream)

        $headerBytes = New-Object System.Collections.Generic.List[byte]
        $tail = New-Object System.Collections.Generic.Queue[byte]
        while ($true) {
            $value = $Stream.ReadByte()
            if ($value -lt 0) {
                throw "Retry mock connection closed before request headers completed."
            }
            $headerBytes.Add([byte]$value)
            $tail.Enqueue([byte]$value)
            while ($tail.Count -gt 4) { $null = $tail.Dequeue() }
            if ($headerBytes.Count -gt 65536) {
                throw "Retry mock request headers exceeded 64 KiB."
            }
            if ($tail.Count -eq 4) {
                $last = $tail.ToArray()
                if ($last[0] -eq 13 -and $last[1] -eq 10 -and $last[2] -eq 13 -and $last[3] -eq 10) {
                    break
                }
            }
        }

        $headerText = [System.Text.Encoding]::ASCII.GetString($headerBytes.ToArray())
        $lines = $headerText -split "`r`n"
        $requestLine = $lines[0]
        if (-not $requestLine -or -not $requestLine.StartsWith("POST /v1/chat/completions ")) {
            throw "Unexpected retry-mock request line: '$requestLine'"
        }

        $contentLength = 0
        foreach ($line in $lines) {
            if ($line -match '^Content-Length:\s*(\d+)\s*$') {
                $contentLength = [int]$Matches[1]
                break
            }
        }

        if ($contentLength -gt 0) {
            $bodyBytes = New-Object byte[] $contentLength
            $offset = 0
            while ($offset -lt $contentLength) {
                $read = $Stream.Read($bodyBytes, $offset, $contentLength - $offset)
                if ($read -le 0) {
                    throw "Retry mock connection closed before request body completed."
                }
                $offset += $read
            }
        }
    }

    function Send-JsonResponse {
        param(
            [System.Net.Sockets.NetworkStream]$Stream,
            [int]$StatusCode,
            [hashtable]$Payload
        )

        $body = $Payload | ConvertTo-Json -Depth 8 -Compress
        $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
        $statusText = if ($StatusCode -eq 200) { "OK" } elseif ($StatusCode -eq 502) { "Bad Gateway" } else { "Error" }
        $header = "HTTP/1.1 $StatusCode $statusText`r`nContent-Type: application/json`r`nContent-Length: $($bodyBytes.Length)`r`nConnection: close`r`n`r`n"
        $headerBytes = [System.Text.Encoding]::ASCII.GetBytes($header)
        $Stream.Write($headerBytes, 0, $headerBytes.Length)
        $Stream.Write($bodyBytes, 0, $bodyBytes.Length)
        $Stream.Flush()
    }

    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $listener.Start()
    $requestCount = 0

    try {
        while ($requestCount -lt 2) {
            $client = $listener.AcceptTcpClient()
            try {
                $client.ReceiveTimeout = 30000
                $client.SendTimeout = 30000
                $stream = $client.GetStream()
                $stream.ReadTimeout = 30000
                $stream.WriteTimeout = 30000

                Read-HttpRequest -Stream $stream
                $requestCount += 1
                [System.IO.File]::WriteAllText($CountFile, [string]$requestCount, [System.Text.Encoding]::ASCII)

                if ($requestCount -eq 1) {
                    Send-JsonResponse -Stream $stream -StatusCode 502 -Payload @{
                        error = @{ message = "Synthetic transient bad gateway for installed retry certification." }
                    }
                    continue
                }

                Send-JsonResponse -Stream $stream -StatusCode 200 -Payload @{
                    id = "chatcmpl-installed-retry-smoke"
                    object = "chat.completion"
                    created = 0
                    model = "installed-retry-smoke-model"
                    choices = @(
                        @{
                            index = 0
                            message = @{
                                role = "assistant"
                                content = "recovered"
                            }
                            finish_reason = "stop"
                        }
                    )
                    usage = @{
                        prompt_tokens = 1
                        completion_tokens = 1
                        total_tokens = 2
                    }
                }
            }
            finally {
                $client.Dispose()
            }
        }
    }
    finally {
        $listener.Stop()
    }
}

try {
    $ready = $false
    $readyDeadline = [DateTime]::UtcNow.AddSeconds(10)
    while ([DateTime]::UtcNow -lt $readyDeadline) {
        $listeners = @(Get-NetTCPConnection -LocalPort $MockPort -State Listen -ErrorAction SilentlyContinue)
        if ($listeners.Count -gt 0) {
            $ready = $true
            break
        }
        if ($mockJob.State -in @('Failed', 'Stopped', 'Completed')) {
            break
        }
        Start-Sleep -Milliseconds 100
    }

    if (-not $ready) {
        $jobOutput = (Receive-Job -Job $mockJob -ErrorAction SilentlyContinue 2>&1 | Out-String).Trim()
        throw "Installed retry mock provider did not become ready. state=$($mockJob.State) output=$jobOutput"
    }

    $payload = @{
        provider_id = "installed-retry-smoke"
        adapter_type = "OPENAI_COMPATIBLE"
        base_url = "http://127.0.0.1:$MockPort/v1"
        model_id = "installed-retry-smoke-model"
    } | ConvertTo-Json -Compress

    $headers = @{ Authorization = "Bearer $BearerToken" }
    $result = Invoke-RestMethod `
        -Uri "$backend/api/settings/models/test" `
        -Method Post `
        -Headers $headers `
        -ContentType "application/json" `
        -Body $payload `
        -TimeoutSec 30

    $requestCount = [int]([System.IO.File]::ReadAllText($countFile, [System.Text.Encoding]::ASCII).Trim())
    if ($result.status -ne "CONNECTED") {
        throw "Installed backend did not recover from transient HTTP 502. status=$($result.status) error=$($result.error) physical_attempts=$requestCount"
    }
    if ($result.model_used -ne "installed-retry-smoke-model") {
        throw "Installed retry smoke returned unexpected model_used='$($result.model_used)'."
    }
    if ($requestCount -ne 2) {
        throw "Installed retry smoke expected exactly 2 physical HTTP attempts (502 then 200); observed $requestCount."
    }

    $null = Wait-Job -Job $mockJob -Timeout 10
    if ($mockJob.State -ne "Completed") {
        $jobOutput = (Receive-Job -Job $mockJob -ErrorAction SilentlyContinue 2>&1 | Out-String).Trim()
        throw "Installed retry mock did not complete cleanly. state=$($mockJob.State) output=$jobOutput"
    }

    $jobErrors = @($mockJob.ChildJobs | ForEach-Object { $_.Error })
    if ($jobErrors.Count -gt 0) {
        $jobOutput = (Receive-Job -Job $mockJob -ErrorAction SilentlyContinue 2>&1 | Out-String).Trim()
        throw "Installed retry mock reported errors. output=$jobOutput"
    }

    Write-Host "INSTALLED_TRANSIENT_RETRY_502_TO_200_OK" -ForegroundColor Green
}
finally {
    if ($mockJob.State -in @('Running', 'NotStarted')) {
        Stop-Job -Job $mockJob -ErrorAction SilentlyContinue
    }
    Remove-Job -Job $mockJob -Force -ErrorAction SilentlyContinue
    Remove-Item -Force $countFile -ErrorAction SilentlyContinue
}
