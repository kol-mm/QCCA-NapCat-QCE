@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem Ensure OneBot HTTP API is available at http://127.0.0.1:3000
powershell -NoProfile -ExecutionPolicy Bypass -File "%cd%\enable-onebot-http.ps1" -Port 3000

set NAPCAT_PATCH_PACKAGE=%cd%\qqnt.json
set NAPCAT_LOAD_PATH=%cd%\loadNapCat.js
set NAPCAT_INJECT_PATH=%cd%\NapCatWinBootHook.dll
set NAPCAT_LAUNCHER_PATH=%cd%\NapCatWinBootMain.exe
set NAPCAT_MAIN_PATH=%cd%\napcat.mjs
set QQ_PATH_CONFIG=%cd%\config\qq_path.txt

if not defined QCE_LOG_DIR set "QCE_LOG_DIR=%cd%\logs"
if not exist "%QCE_LOG_DIR%" mkdir "%QCE_LOG_DIR%"
if not defined QCE_LOG_FILE set "QCE_LOG_FILE=%QCE_LOG_DIR%\qce-runtime.log"
echo [%date% %time%] [launcher] starting >> "%QCE_LOG_FILE%"

:resolve_qq_path
rem Priority 1: Command line argument
if not "%~1"=="" (
    if exist "%~1" (
        set "QQPath=%~1"
        goto :save_and_boot
    ) else (
        echo [Error] Provided QQ path is invalid: %~1
        goto :try_env
    )
)

:try_env
rem Priority 2: Environment variable
if not "%NAPCAT_QQ_PATH%"=="" (
    if exist "!NAPCAT_QQ_PATH!" (
        set "QQPath=!NAPCAT_QQ_PATH!"
        goto :napcat_boot
    ) else (
        echo [Warning] NAPCAT_QQ_PATH is set but invalid: !NAPCAT_QQ_PATH!
    )
)

:try_saved
rem Priority 3: Saved path from previous run
if exist "%QQ_PATH_CONFIG%" (
    set /p SavedPath=<"!QQ_PATH_CONFIG!"
    if exist "!SavedPath!" (
        set "QQPath=!SavedPath!"
        echo [Info] Using saved QQ path: !SavedPath!
        goto :napcat_boot
    )
)

:try_registry
rem Priority 4: Multi-source probe (registry, App Paths, protocol handler,
rem shortcuts) via find-qq.ps1 (issue #589)
if exist "%cd%\find-qq.ps1" (
    for /f "usebackq delims=" %%i in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%cd%\find-qq.ps1" 2^>nul`) do set "QQPath=%%i"
    if not "!QQPath!"=="" if exist "!QQPath!" goto :save_and_boot
)

rem Priority 4b: Direct registry query (fallback when PowerShell is unavailable)
for /f "tokens=2*" %%a in ('reg query "HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ" /v "UninstallString" 2^>nul') do (
    set "RetString=%%~b"
    for %%x in ("!RetString!") do set "pathWithoutUninstall=%%~dpx"
    set "QQPath=!pathWithoutUninstall!QQ.exe"
    if exist "!QQPath!" goto :save_and_boot
)

:try_common_paths
rem Priority 5: Common installation paths
rem Hoist %ProgramFiles(x86)% out of the for-list so the literal `(x86)` does
rem not collide with the surrounding `for ... in (...)` parentheses (#291).
set "PFX86=%ProgramFiles(x86)%"
for %%p in (
    "%ProgramFiles%\Tencent\QQNT\QQ.exe"
    "!PFX86!\Tencent\QQNT\QQ.exe"
    "%LocalAppData%\Programs\Tencent\QQNT\QQ.exe"
    "C:\Program Files\Tencent\QQNT\QQ.exe"
    "D:\Program Files\Tencent\QQNT\QQ.exe"
) do (
    if exist %%p (
        set "QQPath=%%~p"
        goto :save_and_boot
    )
)

:manual_select
echo.
echo ============================================
echo   QQ Installation Not Found
echo ============================================
echo.
echo Could not detect QQ installation automatically.
echo This may happen if you are using a portable/green version of QQ.
echo.
echo If QQ ^(QQNT^) is not installed yet, download it first:
echo   https://im.qq.com/
echo.
echo Options:
echo   [1] Browse for QQ.exe (GUI file picker)
echo   [2] Enter path manually
echo   [3] Exit
echo.
set /p choice="Select option (1/2/3): "

if "%choice%"=="1" goto :gui_select
if "%choice%"=="2" goto :text_input
if "%choice%"=="3" exit /b 1
goto :manual_select

:gui_select
echo.
echo [Info] Opening file picker...
for /f "delims=" %%i in ('powershell -Command "Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.OpenFileDialog; $f.Filter = 'QQ Executable (QQ.exe)|QQ.exe|All Files (*.*)|*.*'; $f.Title = 'Select QQ.exe'; $f.InitialDirectory = 'C:\Program Files'; if ($f.ShowDialog() -eq 'OK') { $f.FileName } else { '' }"') do set "QQPath=%%i"

if "%QQPath%"=="" (
    echo [Error] No file selected.
    goto :manual_select
)
goto :validate_path

:text_input
echo.
set /p "QQPath=Enter full path to QQ.exe: "

:validate_path
if not exist "!QQPath!" (
    echo [Error] File not found: !QQPath!
    goto :manual_select
)

for %%f in ("!QQPath!") do set "filename=%%~nxf"
if /i not "%filename%"=="QQ.exe" (
    echo [Warning] Selected file is not QQ.exe, continue anyway? (Y/N)
    set /p confirm="Confirm: "
    if /i not "!confirm!"=="Y" goto :manual_select
)

:save_and_boot
if not exist "%cd%\config" mkdir "%cd%\config"
echo !QQPath!>"%QQ_PATH_CONFIG%"
echo [Info] QQ path saved to config\qq_path.txt

:napcat_boot
echo.
echo [Info] Using QQ: "!QQPath!"

rem Check if this is QQNT (required) vs old QQ
set "isOldQQ="
if not "!QQPath:\Bin\QQ.exe=!"=="!QQPath!" set "isOldQQ=1"
if defined isOldQQ (
    echo.
    echo ============================================
    echo   [Error] Incompatible QQ Version Detected
    echo ============================================
    echo.
    echo The selected QQ appears to be the OLD version ^(QQ 9.x^).
    echo NapCat requires QQNT ^(QQ 9.9.x or later^).
    echo.
    echo Your path: "!QQPath!"
    echo.
    echo QQNT paths typically look like:
    echo   - C:\Program Files\Tencent\QQNT\QQ.exe
    echo   - %LocalAppData%\Programs\Tencent\QQNT\QQ.exe
    echo.
    echo Please:
    echo   1. Download QQNT from https://im.qq.com/
    echo   2. Run reset-qq-path.bat to clear saved path
    echo   3. Run this launcher again
    echo.
    goto :end_script
)

call :sync_patch_package

echo.

set NAPCAT_MAIN_PATH=%NAPCAT_MAIN_PATH:\=/%
echo (async () =^> {await import("file:///%NAPCAT_MAIN_PATH%")})() > "%NAPCAT_LOAD_PATH%"

rem 回退：部分新版 QQNT 的注入 hook 不再重定向 loadNapCat.js 的读取，
rem 物理复制一份到 QQ 的 resources\app 目录，避免 "Cannot find module ... loadNapCat.js"。
if not "!QQPackageJson!"=="" (
    for %%f in ("!QQPackageJson!") do copy /y "%NAPCAT_LOAD_PATH%" "%%~dpfloadNapCat.js" >nul 2>&1
)

rem ============================================================
rem QCCA - QQ Cloud Control Agent 启动
rem 使用虚拟环境 .venv，国内镜像安装依赖，在新窗口启动 agent
rem ============================================================
echo.
echo ============================================
echo   QCCA - QQ Cloud Control Agent
echo ============================================
echo [Info] 首次启动需要安装 Python 依赖并加载语音模型, 可能需要几分钟, 请不要关闭此窗口.

set "QCCA_DIR=%cd%\qcca"
set "QCCA_VENV=%QCCA_DIR%\.venv"
set "QCCA_PYTHON=%QCCA_VENV%\Scripts\python.exe"
set "QCCA_PYTHONW=%QCCA_VENV%\Scripts\pythonw.exe"
set "QCCA_LOG_DIR=%QCE_LOG_DIR%"
if not exist "%QCCA_LOG_DIR%" mkdir "%QCCA_LOG_DIR%"
set "QCCA_API_LOG=%QCCA_LOG_DIR%\qcca-api.log"
set "QCCA_AGENT_LOG=%QCCA_LOG_DIR%\qcca-agent.log"

rem Prevent a system-wide Python installation from contaminating the venv.
set "PYTHONHOME="
set "PYTHONPATH="

rem 检查 QCCA 模块是否存在
if not exist "%QCCA_DIR%\qq_cloud_control_agent.py" (
    echo [Warning] QCCA module not found, skipping.
    goto :qcca_done
)

rem 检查 Python 是否可用
where python >nul 2>&1
if !errorLevel! neq 0 (
    echo [Warning] Python not found, skipping QCCA.
    echo [Info] Please install Python 3.10+ from https://www.python.org/
    goto :qcca_done
)

rem 创建虚拟环境（如果不存在）
if exist "%QCCA_VENV%\Scripts\python.exe" (
    rem 发行包不能复用另一台电脑生成的虚拟环境，先验证解释器是否可迁移。
    "%QCCA_PYTHON%" -c "import encodings,sys" >nul 2>&1
    if !errorLevel! neq 0 (
        echo [Warning] 检测到损坏或不可迁移的 QCCA 虚拟环境, 正在重建...
        powershell -NoProfile -ExecutionPolicy Bypass -File "%QCCA_DIR%\stop-qcca.ps1" >nul 2>&1
        rmdir /s /q "%QCCA_VENV%" >nul 2>&1
    )
)
if not exist "%QCCA_VENV%\Scripts\python.exe" (
    echo [Info] 检测到首次启动, 正在初始化 QCCA 运行环境...
    echo [Info] Creating Python virtual environment...
    python -m venv --clear "%QCCA_VENV%"
    if not exist "%QCCA_VENV%\Scripts\python.exe" (
        echo [Error] Failed to create virtual environment.
        goto :qcca_done
    )
    echo [Info] Virtual environment created at: %QCCA_VENV%
    "%QCCA_PYTHON%" -c "import encodings,sys" >nul 2>&1
    if !errorLevel! neq 0 (
        echo [Error] 新建的 QCCA 虚拟环境无法启动，请确认 Python 3.10+ 安装完整。
        goto :qcca_done
    )
)

if not defined QCCA_API_PORT set "QCCA_API_PORT=40655"
echo [Info] Starting QCCA API at http://127.0.0.1:!QCCA_API_PORT!/docs ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%QCCA_DIR%\start-services.ps1" -PythonPath "%QCCA_PYTHON%" -QccaDirectory "%QCCA_DIR%" -Port !QCCA_API_PORT! -LogDirectory "%QCCA_LOG_DIR%"
if !errorLevel! neq 0 (
    echo [Error] QCCA service startup failed. See "%QCCA_LOG_DIR%\qcca-api.log.err" and "%QCCA_LOG_DIR%\qcca-agent.log.err".
) else (
    echo [Info] QCCA API and Agent started successfully. Health: http://127.0.0.1:!QCCA_API_PORT!/health
)

:qcca_done
rem Always launch the tray controller, including early exits caused by a
rem missing/broken Python environment. This keeps recovery controls available.
if exist "%QCCA_DIR%\qcca-tray.ps1" (
    set "QCCA_API_PORT=!QCCA_API_PORT!"
    start "QCCA Tray" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "%QCCA_DIR%\qcca-tray.ps1"
)
echo ============================================
rem ============================================================
rem QCCA 启动结束
rem ============================================================

echo.

"%NAPCAT_LAUNCHER_PATH%" "!QQPath!" "%NAPCAT_INJECT_PATH%" %*
goto :end_script

:sync_patch_package
set "QQPackageJson="
set "QQDir="
for %%f in ("!QQPath!") do set "QQDir=%%~dpf"

if exist "!QQDir!resources\app\package.json" (
    set "QQPackageJson=!QQDir!resources\app\package.json"
)

if "!QQPackageJson!"=="" if exist "!QQDir!versions" (
    for /f "delims=" %%d in ('dir /b /ad /o-n "!QQDir!versions" 2^>nul') do (
        if exist "!QQDir!versions\%%d\resources\app\package.json" (
            set "QQPackageJson=!QQDir!versions\%%d\resources\app\package.json"
            goto :sync_patch_package_found
        )
    )
)

:sync_patch_package_found
if "!QQPackageJson!"=="" (
    echo [Warning] QQNT package.json not found, using bundled qqnt.json.
    goto :eof
)

echo [Info] Syncing qqnt.json from installed QQNT metadata...
set "QCE_QQ_PACKAGE_JSON=!QQPackageJson!"
set "QCE_PATCH_PACKAGE=%NAPCAT_PATCH_PACKAGE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop';" ^
    "$source = Get-Content -Raw -LiteralPath $env:QCE_QQ_PACKAGE_JSON | ConvertFrom-Json;" ^
    "$patch = [ordered]@{};" ^
    "foreach ($name in 'name','verHash','version','linuxVersion','linuxVerHash','private','description','productName','author','homepage','sideEffects','bin','buildVersion') { if ($source.PSObject.Properties.Name -contains $name) { $patch[$name] = $source.$name } };" ^
    "$patch['main'] = './loadNapCat.js';" ^
    "$patch['isPureShell'] = $true;" ^
    "$patch['isByteCodeShell'] = $true;" ^
    "$patch['platform'] = 'win32';" ^
    "$patch['eleArch'] = 'x64';" ^
    "$patch | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $env:QCE_PATCH_PACKAGE -Encoding UTF8"

if errorlevel 1 (
    echo [Warning] Failed to refresh qqnt.json, falling back to bundled metadata.
) else (
    echo [Info] qqnt.json refreshed successfully.
)
goto :eof

:end_script

if /i not "%QCCA_HEADLESS%"=="1" pause
exit /b
