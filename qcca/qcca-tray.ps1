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
$findPythonScript = Join-Path $qccaDirectory "find-python.ps1"
$pythonPath = Join-Path $qccaDirectory ".venv\Scripts\python.exe"
$venvDirectory = Join-Path $qccaDirectory ".venv"
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

function Ensure-PythonEnvironment {
    $previousPythonHome = $env:PYTHONHOME
    $previousPythonPath = $env:PYTHONPATH
    $env:PYTHONHOME = $null
    $env:PYTHONPATH = $null
    try {
        if (Test-Path -LiteralPath $pythonPath) {
            & $pythonPath -c "import encodings,sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" *> $null
            if ($LASTEXITCODE -eq 0) { return $true }
            [System.Windows.Forms.MessageBox]::Show(
                "检测到旧的 QCCA 虚拟环境不可用，正在按当前电脑的 Python 重新创建。首次启动可能需要几分钟。",
                "QCCA"
            ) | Out-Null
        }

        $systemPython = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $findPythonScript | Select-Object -First 1
        if (-not $systemPython) {
            throw "未找到兼容的 Python。QCCA 当前需要 Python 3.10、3.11 或 3.12；Python 3.13 及以上暂不支持语音依赖。"
        }
        if (Test-Path -LiteralPath $venvDirectory) {
            Remove-Item -LiteralPath $venvDirectory -Recurse -Force -ErrorAction SilentlyContinue
        }
        & $systemPython -m venv --clear $venvDirectory
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonPath)) {
            throw "无法创建 QCCA 虚拟环境。"
        }
        & $pythonPath -c "import encodings,sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "新建的 QCCA 虚拟环境无法启动。"
        }
        return $true
    } finally {
        $env:PYTHONHOME = $previousPythonHome
        $env:PYTHONPATH = $previousPythonPath
    }
}

function Restart-QccaServices {
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript
        Ensure-PythonEnvironment | Out-Null
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
