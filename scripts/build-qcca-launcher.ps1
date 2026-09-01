param(
    [string]$OutputPath = (Join-Path (Split-Path -Parent $PSScriptRoot) "QCCA-NapCat-QCE.exe")
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $projectRoot "launcher\QccaLauncher.cs"
$iconPath = Join-Path $projectRoot "qcca\qcca-app-icon.ico"
$cscPath = @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe")
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $cscPath) { throw ".NET Framework C# compiler csc.exe was not found." }
if (-not (Test-Path -LiteralPath $sourcePath)) { throw "Launcher source was not found: $sourcePath" }
if (-not (Test-Path -LiteralPath $iconPath)) { throw "QCCA icon was not found: $iconPath" }

$outputDirectory = Split-Path -Parent $OutputPath
if ($outputDirectory) { New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null }

$arguments = @(
    "/nologo",
    "/target:winexe",
    "/out:$OutputPath",
    "/win32icon:$iconPath",
    "/reference:System.Windows.Forms.dll",
    "/reference:System.Web.Extensions.dll",
    $sourcePath
)
& $cscPath @arguments
if ($LASTEXITCODE -ne 0) { throw "QCCA launcher compilation failed with exit code $LASTEXITCODE." }
Write-Host "QCCA launcher created: $OutputPath"
