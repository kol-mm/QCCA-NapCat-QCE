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
        $rawPid = Get-Content -LiteralPath $pidFile -Raw
        $servicePid = 0
        if ([int]::TryParse($rawPid.Trim(), [ref]$servicePid)) { Stop-Tree $servicePid }
        Remove-Item -LiteralPath $pidFile -Force
    }
}

if ($IncludeQQ) {
    & taskkill.exe /IM NapCatWinBootMain.exe /T /F *> $null
    & taskkill.exe /IM QQ.exe /T /F *> $null
}
