param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$OutputLog,
    [Parameter(Mandatory = $true)][string]$ErrorLog
)

$ErrorActionPreference = "Stop"
$arguments = @(
    "-m", "uvicorn", "api_service:app",
    "--host", "127.0.0.1",
    "--port", [string]$Port
)
Start-Process -FilePath $PythonPath -ArgumentList $arguments -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -RedirectStandardOutput $OutputLog -RedirectStandardError $ErrorLog | Out-Null
