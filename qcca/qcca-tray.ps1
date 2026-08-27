Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$qccaDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDirectory = Split-Path -Parent $qccaDirectory
$port = if ($env:QCCA_API_PORT) { $env:QCCA_API_PORT } else { "40655" }
$baseUrl = "http://127.0.0.1:$port"
$stopScript = Join-Path $qccaDirectory "stop-qcca.ps1"
$iconPath = Join-Path $qccaDirectory "qcca-app-icon.ico"

$notifyIcon = New-Object System.Windows.Forms.NotifyIcon
$notifyIcon.Icon = if (Test-Path -LiteralPath $iconPath) {
    New-Object System.Drawing.Icon($iconPath)
} else {
    [System.Drawing.SystemIcons]::Application
}
$notifyIcon.Text = "QCCA - QQ Cloud Control Agent"
$notifyIcon.Visible = $true
$menu = New-Object System.Windows.Forms.ContextMenuStrip

function Open-Url([string]$Url) {
    Start-Process $Url
}

$openPage = $menu.Items.Add("打开 QCCA 管理页面")
$openPage.Add_Click({ Open-Url "$baseUrl/qce/qcca/" })
$openDocs = $menu.Items.Add("打开 API 文档")
$openDocs.Add_Click({ Open-Url "$baseUrl/docs" })
$status = $menu.Items.Add("查看服务状态")
$status.Add_Click({
    try {
        $response = Invoke-WebRequest -Uri "$baseUrl/health" -UseBasicParsing -TimeoutSec 3
        [System.Windows.Forms.MessageBox]::Show("QCCA API 正常运行`n$($response.Content)", "QCCA 状态") | Out-Null
    } catch {
        [System.Windows.Forms.MessageBox]::Show("QCCA API 当前不可用。", "QCCA 状态") | Out-Null
    }
})
$menu.Items.Add("-")
$stop = $menu.Items.Add("停止 QCCA 服务")
$stop.Add_Click({
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript
    $notifyIcon.Visible = $false
    [System.Windows.Forms.Application]::Exit()
})
$exitAll = $menu.Items.Add("退出 QQ、NapCat 和 QCCA")
$exitAll.Add_Click({
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript -IncludeQQ
    $notifyIcon.Visible = $false
    [System.Windows.Forms.Application]::Exit()
})
$menu.Items.Add("-")
$quitTray = $menu.Items.Add("关闭托盘图标")
$quitTray.Add_Click({ $notifyIcon.Visible = $false; [System.Windows.Forms.Application]::Exit() })
$notifyIcon.ContextMenuStrip = $menu
$notifyIcon.Add_DoubleClick({ Open-Url "$baseUrl/qce/qcca/" })

[System.Windows.Forms.Application]::Run()
