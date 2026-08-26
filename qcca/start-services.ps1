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

function Test-PythonImports {
    param([string[]]$Modules)
    $importStatement = "import " + ($Modules -join ", ")
    & $PythonPath -c $importStatement *> $null
    return ($LASTEXITCODE -eq 0)
}

function Install-Requirements {
    param([string]$RequirementsPath, [string]$ErrorLog, [string]$Component)

    $mirrors = @(
        "https://pypi.org/simple",
        "https://pypi.tuna.tsinghua.edu.cn/simple"
    )
    Set-Content -LiteralPath $ErrorLog -Value "[$Component] Python dependencies are missing; starting installation."

    foreach ($mirror in $mirrors) {
        Add-Content -LiteralPath $ErrorLog -Value "[$Component] Trying package index: $mirror"
        $pipArguments = @(
            "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
            "--retries", "2", "--timeout", "30", "-i", $mirror,
            "-r", $RequirementsPath
        )
        if ($mirror -like "*tuna.tsinghua.edu.cn*") {
            $pipArguments += @("--trusted-host", "pypi.tuna.tsinghua.edu.cn")
        }

        & $PythonPath @pipArguments *>> $ErrorLog
        if ($LASTEXITCODE -eq 0) {
            Add-Content -LiteralPath $ErrorLog -Value "[$Component] Dependencies installed successfully."
            return $true
        }
        Add-Content -LiteralPath $ErrorLog -Value "[$Component] Package index failed with exit code $LASTEXITCODE."
    }

    Add-Content -LiteralPath $ErrorLog -Value "[$Component] All package indexes failed. Check network access and the full log above."
    return $false
}

 # Python and pip can emit non-ASCII package metadata on Windows. Force UTF-8
 # so an encoding error does not mask the actual installation failure.
$previousPythonUtf8 = $env:PYTHONUTF8
$env:PYTHONUTF8 = "1"

if (-not (Test-PythonImports @("fastapi", "uvicorn"))) {
    if (-not (Install-Requirements (Join-Path $QccaDirectory "api-requirements.txt") $apiErr "API")) {
        Get-Content -LiteralPath $apiErr -Tail 25 | ForEach-Object { Write-Host $_ }
        exit 1
    }
    if (-not (Test-PythonImports @("fastapi", "uvicorn"))) {
        Add-Content -LiteralPath $apiErr -Value "[API] Dependencies were installed, but fastapi/uvicorn still cannot be imported."
        Get-Content -LiteralPath $apiErr -Tail 25 | ForEach-Object { Write-Host $_ }
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

if (-not (Test-PythonImports @("watchdog", "funasr", "pysilk", "torch", "torchaudio", "requests"))) {
    if (-not (Install-Requirements (Join-Path $QccaDirectory "requirements.txt") $agentErr "Agent")) {
        Add-Content -LiteralPath $agentErr -Value "[Agent] Agent dependencies failed to install; Agent was not started."
        Get-Content -LiteralPath $agentErr -Tail 25 | ForEach-Object { Write-Host $_ }
        exit 1
    }
    if (-not (Test-PythonImports @("watchdog", "funasr", "pysilk", "torch", "torchaudio", "requests"))) {
        Add-Content -LiteralPath $agentErr -Value "[Agent] Dependencies were installed, but one or more Agent modules still cannot be imported."
        Get-Content -LiteralPath $agentErr -Tail 25 | ForEach-Object { Write-Host $_ }
        exit 1
    }
}

Start-HiddenService @("-u", "qq_cloud_control_agent.py") $agentOut $agentErr
if (-not $apiReady) { exit 1 }
$env:PYTHONUTF8 = $previousPythonUtf8
exit 0
