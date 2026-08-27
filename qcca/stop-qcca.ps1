param([switch]$IncludeQQ)

$ErrorActionPreference = "SilentlyContinue"
$qccaDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDirectory = if ($env:QCE_LOG_DIR) { $env:QCE_LOG_DIR } else { Join-Path (Split-Path -Parent $qccaDirectory) "logs" }

function Stop-Tree([int]$ProcessId) {
    if ($ProcessId -gt 0) {
        & taskkill.exe /PID $ProcessId /T /F *> $null
    }
}

foreach ($name in @("api", "agent")) {
    $pidFile = Join-Path $logDirectory "qcca-$name.pid"
    if (Test-Path -LiteralPath $pidFile) {
        $rawPid = (Get-Content -LiteralPath $pidFile -Raw).Trim()
        $servicePid = 0
        $parts = $rawPid -split '\|', 2
        $expectedTicks = 0L
        $validPid = [int]::TryParse($parts[0], [ref]$servicePid)
        $hasIdentity = $parts.Count -eq 2 -and [long]::TryParse($parts[1], [ref]$expectedTicks) -and $expectedTicks -gt 0
        if ($validPid -and $hasIdentity) {
            try {
                $process = Get-Process -Id $servicePid -ErrorAction Stop
                if ($process.StartTime.Ticks -eq $expectedTicks) { Stop-Tree $servicePid }
            } catch { }
        }
        Remove-Item -LiteralPath $pidFile -Force
    }
}

if ($IncludeQQ) {
    & taskkill.exe /IM NapCatWinBootMain.exe /T /F *> $null
    & taskkill.exe /IM QQ.exe /T /F *> $null
}
