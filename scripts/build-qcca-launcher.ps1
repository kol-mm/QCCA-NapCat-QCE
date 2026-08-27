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

if (-not $cscPath) { throw "未找到 .NET Framework C# 编译器 csc.exe。" }
if (-not (Test-Path -LiteralPath $sourcePath)) { throw "找不到启动器源码：$sourcePath" }
if (-not (Test-Path -LiteralPath $iconPath)) { throw "找不到 QCCA 图标：$iconPath" }

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
if ($LASTEXITCODE -ne 0) { throw "QCCA 启动器编译失败，退出码：$LASTEXITCODE" }
Write-Host "QCCA 启动器已生成：$OutputPath"
