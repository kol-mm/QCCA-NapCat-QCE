param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$OutputLog,
    [Parameter(Mandatory = $true)][string]$ErrorLog
)

$ErrorActionPreference = "Stop"
Start-Process -FilePath $PythonPath -ArgumentList @("qq_cloud_control_agent.py") -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -RedirectStandardOutput $OutputLog -RedirectStandardError $ErrorLog | Out-Null
