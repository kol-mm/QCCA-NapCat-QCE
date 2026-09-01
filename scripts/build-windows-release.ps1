param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version = "1.2.0",
    [string]$OutputRoot = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "dist")
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$releaseName = "QCCA-NapCat-QCE-Windows-x64-v$Version"
$outputRootFull = [IO.Path]::GetFullPath($OutputRoot)
$releaseDirectory = [IO.Path]::GetFullPath((Join-Path $outputRootFull $releaseName))
$zipPath = [IO.Path]::GetFullPath((Join-Path $outputRootFull "$releaseName.zip"))

if (-not $releaseDirectory.StartsWith($outputRootFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Release directory is outside the output root: $releaseDirectory"
}

New-Item -ItemType Directory -Path $outputRootFull -Force | Out-Null
if (Test-Path -LiteralPath $releaseDirectory) {
    Remove-Item -LiteralPath $releaseDirectory -Recurse -Force
}
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
New-Item -ItemType Directory -Path $releaseDirectory -Force | Out-Null

$excludedDirectories = @(
    (Join-Path $projectRoot ".git"),
    (Join-Path $projectRoot ".workbuddy"),
    (Join-Path $projectRoot ".idea"),
    (Join-Path $projectRoot ".vscode"),
    (Join-Path $projectRoot "cache"),
    (Join-Path $projectRoot "logs"),
    (Join-Path $projectRoot "launcher"),
    (Join-Path $projectRoot "scripts"),
    (Join-Path $projectRoot "qcca\.venv"),
    (Join-Path $projectRoot "qcca\venv"),
    "__pycache__"
)

$excludedFiles = @(
    (Join-Path $projectRoot ".gitignore"),
    (Join-Path $projectRoot "QCCA-NapCat-QCE.exe"),
    (Join-Path $projectRoot "qce-server.exe.bak"),
    (Join-Path $projectRoot "loadNapCat.js"),
    (Join-Path $projectRoot "qqnt.json"),
    (Join-Path $projectRoot "qcca\async_test.py"),
    (Join-Path $projectRoot "qcca\test.py"),
    (Join-Path $projectRoot "config\qq_path.txt"),
    (Join-Path $projectRoot "config\webui.json")
)

$robocopyArguments = @(
    $projectRoot,
    $releaseDirectory,
    "/E", "/COPY:DAT", "/DCOPY:DAT", "/R:2", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP",
    "/XD"
) + $excludedDirectories + @(
    "/XF"
) + $excludedFiles + @(
    "*.db", "*.db-journal", "*.db-shm", "*.db-wal", "*.sqlite", "*.sqlite3",
    "*.bak", "*.log", "*.pid", "*.pyc", "*.pyo",
    "napcat_*.json", "napcat_protocol_*.json", "onebot11_*.json"
)

& robocopy.exe @robocopyArguments | Out-Null
$robocopyExitCode = $LASTEXITCODE
if ($robocopyExitCode -gt 7) {
    throw "Failed to copy release files. Robocopy exit code: $robocopyExitCode"
}

New-Item -ItemType Directory -Path (Join-Path $releaseDirectory "logs") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $releaseDirectory "cache") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $releaseDirectory "config") -Force | Out-Null

$launcherBuildScript = Join-Path $projectRoot "scripts\build-qcca-launcher.ps1"
$launcherOutput = Join-Path $releaseDirectory "QCCA-NapCat-QCE.exe"
& $launcherBuildScript -OutputPath $launcherOutput

$requiredPaths = @(
    "QCCA-NapCat-QCE.exe",
    "launcher-user.bat",
    "NapCatWinBootMain.exe",
    "NapCatWinBootHook.dll",
    "qce-server.exe",
    "README.md",
    "README.en.md",
    "qcca\api_service.py",
    "qcca\qq_cloud_control_agent.py",
    "qcca\agents\registry.py",
    "qcca\agents\runtime.py",
    "qcca\agents\codex.py",
    "qcca\agents\claude.py",
    "static\qce\qcca\index.html"
)
foreach ($relativePath in $requiredPaths) {
    if (-not (Test-Path -LiteralPath (Join-Path $releaseDirectory $relativePath))) {
        throw "Required release file is missing: $relativePath"
    }
}

$forbiddenItems = Get-ChildItem -LiteralPath $releaseDirectory -Recurse -Force | Where-Object {
    $_.FullName -match '\\qcca\\(?:\.venv|venv)(?:\\|$)' -or
    $_.Name -in @("qq_path.txt", "webui.json", "smtp.json") -or
    $_.Name -match '^(?:napcat|napcat_protocol|onebot11)_\d+\.json$' -or
    $_.Extension -in @(".db", ".sqlite", ".sqlite3") -or
    $_.Name -match '\.db-(?:shm|wal|journal)$'
}
if ($forbiddenItems) {
    $paths = ($forbiddenItems.FullName -join [Environment]::NewLine)
    throw "Release contains forbidden private or generated files:`n$paths"
}

Compress-Archive -LiteralPath $releaseDirectory -DestinationPath $zipPath -CompressionLevel Optimal

$directorySize = (Get-ChildItem -LiteralPath $releaseDirectory -Recurse -File | Measure-Object Length -Sum).Sum
$zipSize = (Get-Item -LiteralPath $zipPath).Length
Write-Host ""
Write-Host "Windows release build completed:"
Write-Host "  Directory: $releaseDirectory"
Write-Host ("  Directory size: {0:N2} MB" -f ($directorySize / 1MB))
Write-Host "  ZIP: $zipPath"
Write-Host ("  ZIP size: {0:N2} MB" -f ($zipSize / 1MB))
