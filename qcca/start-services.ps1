param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$QccaDirectory,
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$LogDirectory
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$apiOut = Join-Path $LogDirectory "qcca-api.log.out"
$apiErr = Join-Path $LogDirectory "qcca-api.log.err"
$agentOut = Join-Path $LogDirectory "qcca-agent.log.out"
$agentErr = Join-Path $LogDirectory "qcca-agent.log.err"

function Start-HiddenService {
    param([string[]]$Arguments, [string]$OutputLog, [string]$ErrorLog)
    Start-Process -FilePath $PythonPath -ArgumentList $Arguments -WorkingDirectory $QccaDirectory -WindowStyle Hidden -RedirectStandardOutput $OutputLog -RedirectStandardError $ErrorLog | Out-Null
}

& $PythonPath -c "import fastapi, uvicorn" *> $null
if ($LASTEXITCODE -ne 0) {
    & (Join-Path (Split-Path $PythonPath) "pip.exe") install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn -r (Join-Path $QccaDirectory "api-requirements.txt") *> $apiErr
    if ($LASTEXITCODE -ne 0) {
        Add-Content -LiteralPath $apiErr -Value "API dependencies failed to install."
        exit 1
    }
}

Start-HiddenService @("-m", "uvicorn", "api_service:app", "--host", "127.0.0.1", "--port", [string]$Port) $apiOut $apiErr
$healthUrl = "http://127.0.0.1:$Port/health"
$apiReady = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $health = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 1
        if ($health.StatusCode -eq 200) { $apiReady = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 250
}
if (-not $apiReady) {
    Add-Content -LiteralPath $apiErr -Value "QCCA API health check failed: $healthUrl"
}

& $PythonPath -c "import watchdog, funasr, pysilk, torch, torchaudio, requests" *> $null
if ($LASTEXITCODE -ne 0) {
    & (Join-Path (Split-Path $PythonPath) "pip.exe") install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn -r (Join-Path $QccaDirectory "requirements.txt") *> $agentErr
    if ($LASTEXITCODE -ne 0) {
        Add-Content -LiteralPath $agentErr -Value "Agent dependencies failed to install; Agent was not started."
        exit 1
    }
}

Start-HiddenService @("qq_cloud_control_agent.py") $agentOut $agentErr
if (-not $apiReady) { exit 1 }
exit 0
