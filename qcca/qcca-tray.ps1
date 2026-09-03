Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$qccaDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDirectory = Split-Path -Parent $qccaDirectory
$qccaPort = if ($env:QCCA_API_PORT) { $env:QCCA_API_PORT } else { "40655" }
$qcePort = if ($env:QCE_SERVER_PORT) { $env:QCE_SERVER_PORT } else { "40653" }
$qccaUrl = "http://127.0.0.1:$qccaPort"
$qceUrl = "http://127.0.0.1:$qcePort"
$qccaPageUrl = "$qccaUrl/qcca/"
$stopScript = Join-Path $qccaDirectory "stop-qcca.ps1"
$startScript = Join-Path $qccaDirectory "start-services.ps1"
$pythonPath = Join-Path $qccaDirectory ".venv\Scripts\python.exe"
$logDirectory = if ($env:QCE_LOG_DIR) { $env:QCE_LOG_DIR } else { Join-Path $rootDirectory "logs" }
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

function Restart-QccaServices {
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        [System.Windows.Forms.MessageBox]::Show("QCCA 虚拟环境不存在，请重新运行启动文件。", "QCCA 重启失败") | Out-Null
        return
    }

    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript
        $startOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript `
            -PythonPath $pythonPath -QccaDirectory $qccaDirectory -Port ([int]$qccaPort) -LogDirectory $logDirectory 2>&1
        if ($LASTEXITCODE -ne 0) {
            $details = ($startOutput | Select-Object -Last 3) -join "`n"
            throw "启动脚本返回代码 $LASTEXITCODE`n$details"
        }

        $health = Invoke-WebRequest -Uri "$qccaUrl/health" -UseBasicParsing -TimeoutSec 5
        if ($health.StatusCode -ne 200) { throw "健康检查返回 HTTP $($health.StatusCode)" }
        [System.Windows.Forms.MessageBox]::Show("QCCA API 和 Agent 已重启。", "QCCA") | Out-Null
    } catch {
        [System.Windows.Forms.MessageBox]::Show("QCCA 重启失败：$($_.Exception.Message)", "QCCA 重启失败") | Out-Null
    }
}

$openPage = $menu.Items.Add("打开 QCCA 管理页面")
$openPage.Add_Click({ Open-Url $qccaPageUrl })
$openDocs = $menu.Items.Add("打开 API 文档")
$openDocs.Add_Click({ Open-Url "$qccaUrl/docs" })
$status = $menu.Items.Add("查看服务状态")
$status.Add_Click({
    try {
        $response = Invoke-WebRequest -Uri "$qccaUrl/health" -UseBasicParsing -TimeoutSec 3
        [System.Windows.Forms.MessageBox]::Show("QCCA API 正常运行`n$($response.Content)", "QCCA 状态") | Out-Null
    } catch {
        [System.Windows.Forms.MessageBox]::Show("QCCA API 当前不可用。", "QCCA 状态") | Out-Null
    }
})
$menu.Items.Add("-")
$restart = $menu.Items.Add("重启 QCCA 服务")
$restart.Add_Click({ Restart-QccaServices })
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
$notifyIcon.Add_DoubleClick({ Open-Url $qccaPageUrl })

[System.Windows.Forms.Application]::Run()
