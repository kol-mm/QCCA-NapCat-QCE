param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$QccaDirectory,
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$LogDirectory
)

$ErrorActionPreference = "Stop"
# PowerShell 7 can promote stderr from native commands to terminating errors.
# Import checks intentionally use a non-zero exit code when a module is absent.
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$apiOut = Join-Path $LogDirectory "qcca-api.log.out"
$apiErr = Join-Path $LogDirectory "qcca-api.log.err"
$agentOut = Join-Path $LogDirectory "qcca-agent.log.out"
$agentErr = Join-Path $LogDirectory "qcca-agent.log.err"

# NapCat scans the shared log directory during startup and expects every
# matching entry to be a file. Older QCCA test runs left directories named
# qcca-test-*, which made NapCat call unlink() on a directory on Windows and
# emit repeated EPERM errors. Remove only stale test directories; normal logs
# and user data are left untouched.
$staleTestCutoff = (Get-Date).AddDays(-7)
Get-ChildItem -LiteralPath $LogDirectory -Directory -Filter "qcca-test-*" -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $staleTestCutoff } |
    ForEach-Object {
        try {
            Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
            Write-Host "[Info] Removed stale QCCA test log directory: $($_.Name)"
        } catch {
            Write-Warning "Could not remove stale QCCA test log directory: $($_.FullName)"
        }
    }

function Start-HiddenService {
    param([string[]]$Arguments, [string]$OutputLog, [string]$ErrorLog)
    return Start-Process -FilePath $PythonPath -ArgumentList $Arguments -WorkingDirectory $QccaDirectory -WindowStyle Hidden -RedirectStandardOutput $OutputLog -RedirectStandardError $ErrorLog -PassThru
}

function Save-ServicePid {
    param([System.Diagnostics.Process]$Process, [string]$Name)
    if ($Process -and $Process.Id) {
        $startTicks = 0
        try { $startTicks = $Process.StartTime.Ticks } catch { }
        Set-Content -LiteralPath (Join-Path $LogDirectory "qcca-$Name.pid") -Value ("{0}|{1}" -f $Process.Id, $startTicks) -Encoding ASCII
    }
}

function Stop-StartedService {
    param([System.Diagnostics.Process]$Process, [string]$Name)
    if ($Process -and -not $Process.HasExited) {
        try { & taskkill.exe /PID $Process.Id /T /F *> $null } catch { }
    }
    $pidFile = Join-Path $LogDirectory "qcca-$Name.pid"
    if (Test-Path -LiteralPath $pidFile) {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }
}

function Test-PythonImports {
    param([string[]]$Modules)
    $importStatement = "import " + ($Modules -join ", ")
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        & $PythonPath -c $importStatement 1>$null 2>$null
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    return ($exitCode -eq 0)
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

        # pip writes warnings such as package deprecations to stderr. Keep that
        # output in the log, but do not let PowerShell treat it as an exception.
        $previousErrorAction = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        try {
            & $PythonPath @pipArguments *>> $ErrorLog
            $pipExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorAction
        }
        if ($pipExitCode -eq 0) {
            Add-Content -LiteralPath $ErrorLog -Value "[$Component] Dependencies installed successfully."
            return $true
        }
        Add-Content -LiteralPath $ErrorLog -Value "[$Component] Package index failed with exit code $pipExitCode."
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

$apiProcess = Start-HiddenService @("-m", "uvicorn", "api_service:app", "--host", "127.0.0.1", "--port", [string]$Port) $apiOut $apiErr
Save-ServicePid $apiProcess "api"
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
    Stop-StartedService $apiProcess "api"
    $env:PYTHONUTF8 = $previousPythonUtf8
    exit 1
}

if (-not (Test-PythonImports @("watchdog", "funasr", "pysilk", "torch", "torchaudio", "requests"))) {
    if (-not (Install-Requirements (Join-Path $QccaDirectory "requirements.txt") $agentErr "Agent")) {
        Add-Content -LiteralPath $agentErr -Value "[Agent] Agent dependencies failed to install; Agent was not started."
        Get-Content -LiteralPath $agentErr -Tail 25 | ForEach-Object { Write-Host $_ }
        Stop-StartedService $apiProcess "api"
        $env:PYTHONUTF8 = $previousPythonUtf8
        exit 1
    }
    if (-not (Test-PythonImports @("watchdog", "funasr", "pysilk", "torch", "torchaudio", "requests"))) {
        Add-Content -LiteralPath $agentErr -Value "[Agent] Dependencies were installed, but one or more Agent modules still cannot be imported."
        Get-Content -LiteralPath $agentErr -Tail 25 | ForEach-Object { Write-Host $_ }
        Stop-StartedService $apiProcess "api"
        $env:PYTHONUTF8 = $previousPythonUtf8
        exit 1
    }
}

try {
    $agentProcess = Start-HiddenService @("-u", "qq_cloud_control_agent.py") $agentOut $agentErr
    Save-ServicePid $agentProcess "agent"
    # Catch immediate import/startup failures instead of reporting a false success.
    Start-Sleep -Milliseconds 750
    $agentProcess.Refresh()
    if ($agentProcess.HasExited) {
        Add-Content -LiteralPath $agentErr -Value "[Agent] Agent exited during startup with code $($agentProcess.ExitCode)."
        Stop-StartedService $agentProcess "agent"
        Stop-StartedService $apiProcess "api"
        $env:PYTHONUTF8 = $previousPythonUtf8
        exit 1
    }
} catch {
    Add-Content -LiteralPath $agentErr -Value "[Agent] Failed to start Agent: $($_.Exception.Message)"
    Stop-StartedService $apiProcess "api"
    $env:PYTHONUTF8 = $previousPythonUtf8
    exit 1
}
$env:PYTHONUTF8 = $previousPythonUtf8
exit 0
