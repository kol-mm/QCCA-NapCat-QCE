$ErrorActionPreference = "SilentlyContinue"

$candidates = New-Object System.Collections.Generic.List[string]

function Add-Candidate([string]$Path) {
    if (-not $Path) { return }
    try { $fullPath = [IO.Path]::GetFullPath($Path) } catch { return }
    if ((Test-Path -LiteralPath $fullPath) -and -not $candidates.Contains($fullPath)) {
        $candidates.Add($fullPath)
    }
}

foreach ($version in @("3.12", "3.11", "3.10")) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $resolved = & $launcher.Source "-$version" -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0) { Add-Candidate ([string]$resolved) }
    }
}

$uv = Get-Command uv.exe -ErrorAction SilentlyContinue
if ($uv) {
    foreach ($version in @("3.12", "3.11", "3.10")) {
        $resolved = & $uv.Source python find $version 2>$null
        if ($LASTEXITCODE -eq 0) { Add-Candidate ([string]$resolved) }
    }
}

foreach ($command in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
    Add-Candidate $command.Source
}

foreach ($base in @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python"),
    "C:\Program Files\Python",
    "C:\Python312",
    "C:\Python311",
    "C:\Python310"
)) {
    if (-not $base -or -not (Test-Path -LiteralPath $base)) { continue }
    if ($base -match 'Python3\d\d$') {
        Add-Candidate (Join-Path $base "python.exe")
    } else {
        Get-ChildItem -LiteralPath $base -Directory -Filter "Python3*" -ErrorAction SilentlyContinue |
            ForEach-Object { Add-Candidate (Join-Path $_.FullName "python.exe") }
    }
}

foreach ($candidate in $candidates) {
    & $candidate -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Output $candidate
        exit 0
    }
}

exit 1
