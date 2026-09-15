param(
    [Parameter(Mandatory = $true)]
    [string]$BackendBaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$BearerToken,

    [int]$MockPort = 18766
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($BearerToken)) {
    throw "Packaged model connection smoke requires a non-empty backend bearer token."
}
if ($MockPort -lt 1 -or $MockPort -gt 65535) {
    throw "MockPort must be between 1 and 65535."
}

$backend = $BackendBaseUrl.TrimEnd('/')
$existingListeners = @(Get-NetTCPConnection -LocalPort $MockPort -State Listen -ErrorAction SilentlyContinue)
if ($existingListeners.Count -gt 0) {
    throw "Mock provider port $MockPort is already occupied before packaged model connection smoke."
}

Write-Host "== Packaged backend model connection smoke ==" -ForegroundColor Cyan
Write-Host "Starting one-shot loopback OpenAI-compatible provider on 127.0.0.1:$MockPort"

$mockJob = Start-Job -ArgumentList $MockPort -ScriptBlock {
    param([int]$Port)

    $ErrorActionPreference = "Stop"
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $listener.Start()

    try {
        $client = $listener.AcceptTcpClient()
        try {
            $stream = $client.GetStream()
            $reader = [System.IO.StreamReader]::new(
                $stream,
                [System.Text.Encoding]::UTF8,
                $false,
                4096,
                $true
            )

            $requestLine = $reader.ReadLine()
            if (-not $requestLine -or -not $requestLine.StartsWith("POST /v1/chat/completions ")) {
                throw "Unexpected mock-provider request line: '$requestLine'"
            }

            $contentLength = 0
            while ($true) {
                $line = $reader.ReadLine()
                if ($null -eq $line) {
                    throw "Mock provider connection closed before request headers completed."
                }
                if ($line.Length -eq 0) {
                    break
                }
                if ($line -match '^Content-Length:\s*(\d+)\s*$') {
                    $contentLength = [int]$Matches[1]
                }
            }

            if ($contentLength -gt 0) {
                $bodyChars = New-Object char[] $contentLength
                $offset = 0
                while ($offset -lt $contentLength) {
                    $read = $reader.Read($bodyChars, $offset, $contentLength - $offset)
                    if ($read -le 0) {
                        break
                    }
                    $offset += $read
                }
                if ($offset -lt $contentLength) {
                    throw "Mock provider received only $offset of $contentLength request body characters."
                }
            }

            $responseObject = @{
                id = "chatcmpl-release-smoke"
                object = "chat.completion"
                created = 0
                model = "smoke-model"
                choices = @(
                    @{
                        index = 0
                        message = @{
                            role = "assistant"
                            content = "pong"
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
            $body = $responseObject | ConvertTo-Json -Depth 8 -Compress
            $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
            $header = "HTTP/1.1 200 OK`r`nContent-Type: application/json`r`nContent-Length: $($bodyBytes.Length)`r`nConnection: close`r`n`r`n"
            $headerBytes = [System.Text.Encoding]::ASCII.GetBytes($header)

            $stream.Write($headerBytes, 0, $headerBytes.Length)
            $stream.Write($bodyBytes, 0, $bodyBytes.Length)
            $stream.Flush()
        }
        finally {
            $client.Dispose()
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
        throw "Loopback mock provider did not become ready. job_state=$($mockJob.State) output=$jobOutput"
    }

    $payload = @{
        provider_id = "release-smoke"
        adapter_type = "OPENAI_COMPATIBLE"
        base_url = "http://127.0.0.1:$MockPort/v1"
        model_id = "smoke-model"
    } | ConvertTo-Json -Compress

    $headers = @{
        Authorization = "Bearer $BearerToken"
    }

    $invokeArgs = @{
        Uri = "$backend/api/settings/models/test"
        Method = "Post"
        Headers = $headers
        ContentType = "application/json"
        Body = $payload
        TimeoutSec = 20
    }
    $result = Invoke-RestMethod @invokeArgs

    if ($result.status -ne "CONNECTED") {
        throw "Packaged model connection smoke failed: status=$($result.status) error=$($result.error)"
    }
    if ($result.model_used -ne "smoke-model") {
        throw "Packaged model connection smoke returned unexpected model_used='$($result.model_used)'."
    }

    $null = Wait-Job -Job $mockJob -Timeout 10
    if ($mockJob.State -ne "Completed") {
        $jobOutput = (Receive-Job -Job $mockJob -ErrorAction SilentlyContinue 2>&1 | Out-String).Trim()
        throw "Loopback mock provider did not complete cleanly. state=$($mockJob.State) output=$jobOutput"
    }

    $jobErrors = @($mockJob.ChildJobs | ForEach-Object { $_.Error })
    if ($jobErrors.Count -gt 0) {
        $jobOutput = (Receive-Job -Job $mockJob -ErrorAction SilentlyContinue 2>&1 | Out-String).Trim()
        throw "Loopback mock provider reported errors. output=$jobOutput"
    }

    Write-Host "PACKAGED_MODEL_CONNECTION_TEST_OK" -ForegroundColor Green
}
finally {
    if ($mockJob.State -in @('Running', 'NotStarted')) {
        Stop-Job -Job $mockJob -ErrorAction SilentlyContinue
    }
    Remove-Job -Job $mockJob -Force -ErrorAction SilentlyContinue
}
