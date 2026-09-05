param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$QccaDirectory,
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$LogDirectory
)

$ErrorActionPreference = "Stop"
# Keep host output aligned with the UTF-8 launcher code page. This affects
# visible startup diagnostics; service logs are written explicitly as UTF-8.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
# Normalize the key casing because some launchers provide both PATH and Path;
# Windows PowerShell 5 Start-Process rejects that duplicate environment block.
$env:Path = $env:PATH
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
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"

function Initialize-LogFile {
    param([string]$PreferredPath)

    # NapCat or a previous service can briefly keep the normal log open. Do
    # not fail the whole QCCA startup in that case; use a per-run log file.
    try {
        $stream = [IO.File]::Open(
            $PreferredPath,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
        try { $stream.SetLength(0) } finally { $stream.Dispose() }
        return $PreferredPath
    } catch {
        $directory = Split-Path -Parent $PreferredPath
        $baseName = [IO.Path]::GetFileNameWithoutExtension($PreferredPath)
        $extension = [IO.Path]::GetExtension($PreferredPath)
        $fallbackPath = Join-Path $directory ("{0}-{1}{2}" -f $baseName, $runStamp, $extension)
        try {
            $fallbackStream = [IO.File]::Open(
                $fallbackPath,
                [IO.FileMode]::Create,
                [IO.FileAccess]::Write,
                [IO.FileShare]::ReadWrite
            )
            $fallbackStream.Dispose()
            Write-Host "[Warning] Log file is locked: $PreferredPath"
            Write-Host "[Info] Using per-run log file: $fallbackPath"
            return $fallbackPath
        } catch {
            throw "无法创建 QCCA 日志文件：$PreferredPath；备用路径也不可用：$fallbackPath。$($_.Exception.Message)"
        }
    }
}

function Write-Diagnostic {
    param([string]$Path, [string]$Message)
    try {
        [IO.File]::AppendAllText($Path, $Message + [Environment]::NewLine, $utf8NoBom)
    } catch {
        Write-Host "[Warning] Could not write diagnostic log: $Path"
        Write-Host $Message
    }
}

function Stop-ExistingQccaProcesses {
    # A forced console close can leave either service alive without a PID file.
    # Stop only Python processes launched from this QCCA virtualenv so an
    # unrelated system Python process is never touched. This also releases
    # redirected log handles before Start-Process opens the same files again.
    $pythonFullPath = [IO.Path]::GetFullPath($PythonPath)
    $processIds = [System.Collections.Generic.HashSet[int]]::new()

    foreach ($name in @("api", "agent")) {
        $pidFile = Join-Path $LogDirectory "qcca-$name.pid"
        if (Test-Path -LiteralPath $pidFile) {
            try {
                $raw = (Get-Content -LiteralPath $pidFile -Raw -ErrorAction Stop).Trim()
                $pidValue = 0
                if ([int]::TryParse(($raw -split '\|', 2)[0], [ref]$pidValue)) {
                    try {
                        $recordedProcess = Get-Process -Id $pidValue -ErrorAction Stop
                        if ([IO.Path]::GetFullPath($recordedProcess.Path) -ieq $pythonFullPath) {
                            [void]$processIds.Add($pidValue)
                        }
                    } catch { }
                }
            } catch { }
        }
    }

    # Include any matching virtualenv process even when its PID file was lost.
    foreach ($candidate in @(Get-Process -Name "python", "python3" -ErrorAction SilentlyContinue)) {
        try {
            if ([IO.Path]::GetFullPath($candidate.Path) -ieq $pythonFullPath) {
                [void]$processIds.Add($candidate.Id)
            }
        } catch { }
    }

    # Also inspect the configured API port. Do not terminate another program
    # that happens to use the same port unless its executable is this Python.
    foreach ($listener in @(Get-NetTCPConnection -State Listen -LocalAddress "127.0.0.1" -LocalPort $Port -ErrorAction SilentlyContinue)) {
        try {
            $owner = Get-Process -Id $listener.OwningProcess -ErrorAction Stop
            if ([IO.Path]::GetFullPath($owner.Path) -ieq $pythonFullPath) {
                [void]$processIds.Add($owner.Id)
            }
        } catch { }
    }

    foreach ($processId in $processIds) {
        try {
            $process = Get-Process -Id $processId -ErrorAction Stop
            Write-Host "[Info] Stopping previous QCCA service process (PID $processId)..."
            & taskkill.exe /PID $processId /T /F *> $null
        } catch { }
    }

    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        $remaining = @(Get-Process -Name "python", "python3" -ErrorAction SilentlyContinue | Where-Object {
            try { [IO.Path]::GetFullPath($_.Path) -ieq $pythonFullPath } catch { $false }
        })
        $stillListening = @(Get-NetTCPConnection -State Listen -LocalAddress "127.0.0.1" -LocalPort $Port -ErrorAction SilentlyContinue)
        if ($remaining.Count -eq 0 -and $stillListening.Count -eq 0) { break }
        Start-Sleep -Milliseconds 100
    }

    $remaining = @(Get-Process -Name "python", "python3" -ErrorAction SilentlyContinue | Where-Object {
        try { [IO.Path]::GetFullPath($_.Path) -ieq $pythonFullPath } catch { $false }
    })
    if ($remaining.Count -gt 0) {
        $ids = ($remaining | ForEach-Object { $_.Id }) -join ", "
        throw "无法停止旧的 QCCA 服务进程（PID $ids）。请以管理员身份运行启动器，或先在任务管理器中结束这些进程。"
    }

    foreach ($name in @("api", "agent")) {
        Remove-Item -LiteralPath (Join-Path $LogDirectory "qcca-$name.pid") -Force -ErrorAction SilentlyContinue
    }
}

Stop-ExistingQccaProcesses

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

# Start each run with clean UTF-8 log files. Older PowerShell redirection used
# UTF-16LE, whose NUL bytes otherwise remain visible in the next run's logs.
$apiOut = Initialize-LogFile $apiOut
$apiErr = Initialize-LogFile $apiErr
$agentOut = Initialize-LogFile $agentOut
$agentErr = Initialize-LogFile $agentErr

function Start-HiddenService {
    param([string[]]$Arguments, [string]$OutputLog, [string]$ErrorLog)
    return Start-Process -FilePath $PythonPath -ArgumentList $Arguments -WorkingDirectory $QccaDirectory `
        -WindowStyle Hidden -RedirectStandardOutput $OutputLog -RedirectStandardError $ErrorLog -PassThru
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
    param([string[]]$Modules, [string]$ErrorLog = "")
    $importStatement = "import " + ($Modules -join ", ")
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        $importOutput = @(& $PythonPath -c $importStatement 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($exitCode -ne 0 -and $ErrorLog -and $importOutput.Count -gt 0) {
        Write-Diagnostic $ErrorLog ("[Python import check] " + (($importOutput | ForEach-Object { [string]$_ }) -join "`n"))
    }
    return ($exitCode -eq 0)
}

function Install-Requirements {
    param([string]$RequirementsPath, [string]$ErrorLog, [string]$Component)

    $mirrors = @(
        "https://pypi.org/simple",
        "https://pypi.tuna.tsinghua.edu.cn/simple"
    )
    Set-Content -LiteralPath $ErrorLog -Value "[$Component] Python dependencies are missing; starting installation." -Encoding UTF8

    foreach ($mirror in $mirrors) {
        Write-Diagnostic $ErrorLog "[$Component] Trying package index: $mirror"
        $pipArguments = @(
            "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
            "--retries", "2", "--timeout", "30", "-i", $mirror,
            "-r", $RequirementsPath
        )
        if ($mirror -like "*tuna.tsinghua.edu.cn*") {
            $pipArguments += @("--trusted-host", "pypi.tuna.tsinghua.edu.cn")
        }

        # Do not use PowerShell 5's *>> redirection here: it writes UTF-16LE,
        # which appears as garbled text when the log is opened as UTF-8.
        $pipStdout = Join-Path $LogDirectory (".qcca-{0}-pip-{1}.out" -f $Component, $PID)
        $pipStderr = Join-Path $LogDirectory (".qcca-{0}-pip-{1}.err" -f $Component, $PID)
        try {
            $pipProcess = Start-Process -FilePath $PythonPath -ArgumentList $pipArguments -WorkingDirectory $QccaDirectory `
                -WindowStyle Hidden -RedirectStandardOutput $pipStdout -RedirectStandardError $pipStderr -PassThru
            $startedAt = Get-Date
            while (-not $pipProcess.HasExited) {
                Start-Sleep -Seconds 5
                $elapsed = [int]((Get-Date) - $startedAt).TotalSeconds
                Write-Host "[Info] $Component dependencies are still installing ($elapsed seconds)..."
            }
            $pipProcess.WaitForExit()
            $pipExitCode = $pipProcess.ExitCode
            foreach ($pipLog in @($pipStdout, $pipStderr)) {
                if (Test-Path -LiteralPath $pipLog) {
                    $text = [IO.File]::ReadAllText($pipLog, [Text.Encoding]::UTF8)
                    if ($text) { Write-Diagnostic $ErrorLog $text }
                }
            }
        } finally {
            Remove-Item -LiteralPath $pipStdout, $pipStderr -Force -ErrorAction SilentlyContinue
        }
        if ($pipExitCode -eq 0) {
            Write-Diagnostic $ErrorLog "[$Component] Dependencies installed successfully."
            return $true
        }
        Write-Diagnostic $ErrorLog "[$Component] Package index failed with exit code $pipExitCode."
    }

    Write-Diagnostic $ErrorLog "[$Component] All package indexes failed. Check network access and the full log above."
    return $false
}

 # Python and pip can emit non-ASCII package metadata on Windows. Force UTF-8
 # so an encoding error does not mask the actual installation failure.
$previousPythonUtf8 = $env:PYTHONUTF8
$env:PYTHONUTF8 = "1"

if (-not (Test-PythonImports @("fastapi", "uvicorn") $apiErr)) {
    if (-not (Install-Requirements (Join-Path $QccaDirectory "api-requirements.txt") $apiErr "API")) {
        Get-Content -LiteralPath $apiErr -Tail 25 | ForEach-Object { Write-Host $_ }
        exit 1
    }
    if (-not (Test-PythonImports @("fastapi", "uvicorn") $apiErr)) {
        Write-Diagnostic $apiErr "[API] Dependencies were installed, but fastapi/uvicorn still cannot be imported."
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
        $apiProcess.Refresh()
        if ($apiProcess.HasExited) { break }
        $apiListener = @(Get-NetTCPConnection -State Listen -LocalAddress "127.0.0.1" -LocalPort $Port -ErrorAction SilentlyContinue)
        if ($apiListener.Count -eq 0) {
            Start-Sleep -Milliseconds 250
            continue
        }
        $health = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 1
        if ($health.StatusCode -eq 200) { $apiReady = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 250
}
if (-not $apiReady) {
        Write-Diagnostic $apiErr "QCCA API health check failed: $healthUrl"
    Stop-StartedService $apiProcess "api"
    $env:PYTHONUTF8 = $previousPythonUtf8
    exit 1
}

if (-not (Test-PythonImports @("watchdog", "funasr", "pysilk", "torch", "torchaudio", "requests") $agentErr)) {
    if (-not (Install-Requirements (Join-Path $QccaDirectory "requirements.txt") $agentErr "Agent")) {
        Write-Diagnostic $agentErr "[Agent] Agent dependencies failed to install; Agent was not started."
        Get-Content -LiteralPath $agentErr -Tail 25 | ForEach-Object { Write-Host $_ }
        Stop-StartedService $apiProcess "api"
        $env:PYTHONUTF8 = $previousPythonUtf8
        exit 1
    }
    if (-not (Test-PythonImports @("watchdog", "funasr", "pysilk", "torch", "torchaudio", "requests") $agentErr)) {
        Write-Diagnostic $agentErr "[Agent] Dependencies were installed, but one or more Agent modules still cannot be imported."
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
        Write-Diagnostic $agentErr "[Agent] Agent exited during startup with code $($agentProcess.ExitCode)."
        Stop-StartedService $agentProcess "agent"
        Stop-StartedService $apiProcess "api"
        $env:PYTHONUTF8 = $previousPythonUtf8
        exit 1
    }
} catch {
    Write-Diagnostic $agentErr "[Agent] Failed to start Agent: $($_.Exception.Message)"
    Stop-StartedService $apiProcess "api"
    $env:PYTHONUTF8 = $previousPythonUtf8
    exit 1
}
$env:PYTHONUTF8 = $previousPythonUtf8
exit 0
