param(
    [Parameter(Mandatory = $true)]
    [string]$BackendBaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$BearerToken,

    [int]$MockPort = 18767
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($BearerToken)) {
    throw "Packaged full-workflow smoke requires a non-empty backend bearer token."
}
if ($MockPort -lt 1 -or $MockPort -gt 65535) {
    throw "MockPort must be between 1 and 65535."
}

$backend = $BackendBaseUrl.TrimEnd('/')
$existingListeners = @(Get-NetTCPConnection -LocalPort $MockPort -State Listen -ErrorAction SilentlyContinue)
if ($existingListeners.Count -gt 0) {
    throw "Mock provider port $MockPort is already occupied before packaged full-workflow smoke."
}

Write-Host "== Packaged backend full-workflow smoke ==" -ForegroundColor Cyan
Write-Host "Starting loopback OpenAI-compatible provider on 127.0.0.1:$MockPort"

$countFile = Join-Path ([System.IO.Path]::GetTempPath()) ("ai-marketing-full-workflow-count-{0}.txt" -f ([Guid]::NewGuid().ToString("N")))
[System.IO.File]::WriteAllText($countFile, "0", [System.Text.Encoding]::ASCII)

$mockJob = Start-Job -ArgumentList $MockPort, $countFile -ScriptBlock {
    param([int]$Port, [string]$CountFile)

    $ErrorActionPreference = "Stop"
    Set-StrictMode -Version Latest

    $responses = @(
        "# Synthetic CMO Plan`nPackaged workflow certification planning placeholder.",
        "Synthetic intelligence planning placeholder for packaged workflow certification.",
        "Synthetic content planning placeholder for packaged workflow certification.",
        "Synthetic creative planning placeholder for packaged workflow certification.",
        "Synthetic measurement and attribution planning placeholder for packaged workflow certification.",
        "Synthetic experimentation and governance planning placeholder for packaged workflow certification.",
        "# Synthetic Final GTM Plan`nPackaged workflow certification planning placeholder."
    )

    function Read-HttpRequest {
        param([System.Net.Sockets.NetworkStream]$Stream)

        $headerBytes = New-Object System.Collections.Generic.List[byte]
        $tail = New-Object System.Collections.Generic.Queue[byte]
        while ($true) {
            $value = $Stream.ReadByte()
            if ($value -lt 0) {
                throw "Mock provider connection closed before request headers completed."
            }
            $headerBytes.Add([byte]$value)
            $tail.Enqueue([byte]$value)
            while ($tail.Count -gt 4) { $null = $tail.Dequeue() }
            if ($headerBytes.Count -gt 65536) {
                throw "Mock provider request headers exceeded 64 KiB."
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
            throw "Unexpected mock-provider request line: '$requestLine'"
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
                    throw "Mock provider connection closed before request body completed."
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
        $statusText = if ($StatusCode -eq 200) { "OK" } else { "Internal Server Error" }
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
        while ($true) {
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

                if ($requestCount -gt 7) {
                    Send-JsonResponse -Stream $stream -StatusCode 500 -Payload @{
                        error = @{ message = "Unexpected model request beyond canonical seven-call workflow." }
                    }
                    continue
                }

                Send-JsonResponse -Stream $stream -StatusCode 200 -Payload @{
                    id = "chatcmpl-full-workflow-$requestCount"
                    object = "chat.completion"
                    created = 0
                    model = "workflow-smoke-model"
                    choices = @(
                        @{
                            index = 0
                            message = @{
                                role = "assistant"
                                content = $responses[$requestCount - 1]
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
        throw "Loopback full-workflow mock provider did not become ready. job_state=$($mockJob.State) output=$jobOutput"
    }

    $headers = @{
        Authorization = "Bearer $BearerToken"
    }

    $settings = Invoke-RestMethod -Uri "$backend/api/settings/models" -Method Get -Headers $headers -TimeoutSec 20
    $providerId = "release-workflow-smoke"
    $modelId = "workflow-smoke-model"
    $settingsPayload = @{
        revision = [int]$settings.settings_revision
        free_only_mode = $true
        global_target = @{
            provider_id = $providerId
            model_id = $modelId
        }
        agent_overrides = @{}
        fallback_chain = @()
        providers = @(
            @{
                provider_id = $providerId
                adapter_type = "OPENAI_COMPATIBLE"
                display_name = "Release Workflow Smoke"
                base_url = "http://127.0.0.1:$MockPort/v1"
                enabled = $true
                default_model = $modelId
                chat_completions_path = "/chat/completions"
                cost_policy = "FREE_TIER_ALLOWED"
                timeout_seconds = 20.0
            }
        )
    } | ConvertTo-Json -Depth 10 -Compress

    $saved = Invoke-RestMethod -Uri "$backend/api/settings/models" -Method Put -Headers $headers -ContentType "application/json" -Body $settingsPayload -TimeoutSec 20
    if ($saved.global_target.provider_id -ne $providerId -or $saved.global_target.model_id -ne $modelId) {
        throw "Packaged full-workflow smoke could not persist the loopback provider as global target."
    }

    $campaignPayload = @{
        business_id = "BIZ_RELEASE_WORKFLOW_SMOKE"
        objective = "Create a synthetic planning-only marketing workflow for packaged release certification. Do not state product facts, observed metrics, rankings, comparative claims, or deployment claims."
    } | ConvertTo-Json -Compress

    $result = Invoke-RestMethod -Uri "$backend/api/campaigns/execute_supervised" -Method Post -Headers $headers -ContentType "application/json" -Body $campaignPayload -TimeoutSec 180

    $requestCount = [int]([System.IO.File]::ReadAllText($countFile, [System.Text.Encoding]::ASCII).Trim())
    if ($requestCount -ne 7) {
        throw "Canonical packaged workflow must issue exactly 7 model requests; observed $requestCount."
    }

    $expectedStages = @("cmo_initial", "intelligence", "content", "creative", "performance", "final_cmo")
    $actualStages = @($result.stages_completed)
    if ($actualStages.Count -ne $expectedStages.Count) {
        throw "Canonical packaged workflow must complete exactly 6 logical stages; observed $($actualStages.Count): $($actualStages -join ', ')."
    }
    for ($i = 0; $i -lt $expectedStages.Count; $i++) {
        if ([string]$actualStages[$i] -ne $expectedStages[$i]) {
            throw "Canonical stage order mismatch at index $i. expected='$($expectedStages[$i])' actual='$($actualStages[$i])'."
        }
    }

    if ($result.status -ne "COMPLETED" -or -not $result.success) {
        throw "Packaged full-workflow smoke did not complete successfully. status=$($result.status) success=$($result.success)"
    }

    Write-Host "PACKAGED_FULL_WORKFLOW_6_STAGE_7_CALL_OK" -ForegroundColor Green
}
finally {
    if ($mockJob.State -in @('Running', 'NotStarted')) {
        Stop-Job -Job $mockJob -ErrorAction SilentlyContinue
    }
    Remove-Job -Job $mockJob -Force -ErrorAction SilentlyContinue
    Remove-Item -Force $countFile -ErrorAction SilentlyContinue
}
