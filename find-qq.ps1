$ErrorActionPreference = 'SilentlyContinue'

$candidates = New-Object System.Collections.Generic.List[string]

function Add-Candidate([string]$path) {
    if ($path) { $script:candidates.Add($path.Trim('"').Trim()) }
}

# 1) Uninstall registry entries (64-bit, 32-bit and per-user installs)
foreach ($key in @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ'
)) {
    $props = Get-ItemProperty -LiteralPath $key
    if (-not $props) { continue }
    if ($props.DisplayIcon) { Add-Candidate ($props.DisplayIcon -replace ',\d+$', '') }
    if ($props.UninstallString) {
        $dir = Split-Path -Parent ($props.UninstallString.Trim('"'))
        if ($dir) { Add-Candidate (Join-Path $dir 'QQ.exe') }
    }
    if ($props.InstallLocation) { Add-Candidate (Join-Path $props.InstallLocation 'QQ.exe') }
}

# 2) App Paths
foreach ($key in @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\QQ.exe',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\QQ.exe'
)) {
    Add-Candidate (Get-ItemProperty -LiteralPath $key).'(default)'
}

# 3) tencent:// protocol handler: points inside versions\<ver>\resources\app,
#    so walk up the directory tree probing for QQ.exe at each level.
$proto = (Get-ItemProperty -LiteralPath 'Registry::HKEY_CLASSES_ROOT\Tencent\shell\open\command').'(default)'
if ($proto -match '"([^"]+)"') {
    $dir = Split-Path -Parent $Matches[1]
    for ($i = 0; $i -lt 6 -and $dir; $i++) {
        Add-Candidate (Join-Path $dir 'QQ.exe')
        $dir = Split-Path -Parent $dir
    }
}

# 4) Start menu and desktop shortcuts
$shell = New-Object -ComObject WScript.Shell
foreach ($root in @(
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs",
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs",
    "$env:USERPROFILE\Desktop",
    "$env:PUBLIC\Desktop"
)) {
    Get-ChildItem -LiteralPath $root -Filter '*QQ*.lnk' -Recurse -Depth 2 |
        ForEach-Object { Add-Candidate $shell.CreateShortcut($_.FullName).TargetPath }
}

# 5) Common installation directories
foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, "$env:LocalAppData\Programs", 'D:\Program Files')) {
    if ($base) { Add-Candidate (Join-Path $base 'Tencent\QQNT\QQ.exe') }
}

foreach ($candidate in $candidates) {
    if ((Split-Path -Leaf $candidate) -ieq 'QQ.exe' -and (Test-Path -LiteralPath $candidate)) {
        Write-Output $candidate
        exit 0
    }
}
