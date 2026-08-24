param([int]$Port = 3000)

$configDir = Join-Path $PSScriptRoot 'config'
$files = Get-ChildItem -LiteralPath $configDir -Filter 'onebot11*.json' -File -ErrorAction SilentlyContinue
foreach ($file in $files) {
    try {
        $config = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -eq $config.network) { $config | Add-Member -NotePropertyName network -NotePropertyValue ([pscustomobject]@{}) }
        if ($null -eq $config.network.httpServers) { $config.network | Add-Member -NotePropertyName httpServers -NotePropertyValue @() }
        $server = @($config.network.httpServers) | Where-Object { $_.port -eq $Port } | Select-Object -First 1
        if ($null -eq $server) {
            $server = [pscustomobject]@{ name='QCE 本地接口'; enable=$true; host='127.0.0.1'; port=$Port; enableCors=$true; enableWebsocket=$false; messagePostFormat='array'; reportSelfMessage=$false; token='' }
            $config.network.httpServers = @($config.network.httpServers) + $server
        } else {
            $server.enable = $true
            $server.host = '127.0.0.1'
            $server.enableCors = $true
            $server.enableWebsocket = $false
        }
        $config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $file.FullName -Encoding UTF8
    } catch { Write-Host "[Warning] Failed to update $($file.Name): $($_.Exception.Message)" }
}
