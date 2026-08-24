==================================================
QCCA-NapCat-QCE - 完整包
==================================================
基于 NapCat + QQ Chat Exporter，集成 QCCA 模块

NapCat 版本: v4.18.19
QCE 版本: 5.5.80
平台: Windows-x64
构建时间: 2026-08-17 17:37:53
==================================================

包含内容:

- NapCat v4.18.19
- QQ Chat Exporter 插件 5.5.80
- QCCA (QQ Cloud Control Agent) 模块
- QCCA FastAPI 管理服务
- 预配置的 Web 界面
- 独立模式支持（无需登录QQ）

--------------------------------------------------
原作者信息
--------------------------------------------------
NapCat: https://github.com/NapNeko/NapCatQQ
QCE 插件: https://github.com/shuakami/qq-chat-exporter

本项目基于上述开源项目，保留原作者信息。
本项目遵循 GPL-v3 协议 (GNU General Public License v3)。
详见: https://www.gnu.org/licenses/gpl-3.0.html

--------------------------------------------------
QCCA 模块说明
--------------------------------------------------
QCCA (QQ Cloud Control Agent) 监听 QCE live-capture 导出的
JSONL 文件，自动处理文本和语音消息:
  - 文本消息: 直接交给 Codex Agent 处理
  - 语音消息: 通过 FunASR 语音识别转为文本后处理
  - 处理结果通过 QQ 邮箱 SMTP 回复对应用户

QCCA 依赖:
  - Python 3.8+
  - watchdog, funasr, pysilk, torch, torchaudio
  - fastapi, uvicorn
  - ffmpeg (用于 amr 转 wav)
  - 启动时自动创建 venv 虚拟环境并安装依赖

--------------------------------------------------
使用方法
--------------------------------------------------
1. 解压到任意目录

2. 完整模式 (推荐): 运行 launcher-user.bat
   - 需要登录QQ，支持导出新记录
   - 自动启动 QCCA agent 和管理 API（不额外打开 Python 黑窗）
   - 第一次接触项目的小白用户优先用这个

   如需完全隐藏启动器窗口，运行 `启动QCCA隐藏.vbs`。
   该方式仍会启动 NapCat，但不会显示 QCCA 的控制台窗口；运行状态可通过 QCE 日志和
   http://127.0.0.1:40655/docs 检查。

3. 独立模式: 运行 start-standalone.bat
   - 无需登录，仅浏览已导出文件
   - 不启动 QCCA

4. 浏览器访问: http://localhost:40653/qce
   完整模式需输入控制台显示的访问令牌

5. QCCA 管理页面: http://localhost:40653/qce/qcca/
   - 查看 QCCA 配置中的 QQ 用户、工作区和会话
   - 修改沙箱权限和最近使用的工作区/会话
   - 工作目录和会话由 QCCA 自动维护，管理页面为只读

6. QCCA API 文档: http://127.0.0.1:40655/docs

--------------------------------------------------
启动流程 (launcher-user.bat)
--------------------------------------------------
1. 检测 QQ 安装路径
2. 同步 QQNT 版本信息到 qqnt.json
3. 启动 QCCA 模块:
   a. 检查 Python 环境
   b. 创建 venv 虚拟环境 (qcca\venv)
   c. 使用国内镜像 (清华源) 安装 requirements.txt
   d. 在新窗口启动 qq_cloud_control_agent.py
4. 在新窗口启动 QCCA FastAPI 管理服务 (127.0.0.1:40655)
5. 启动 NapCat (注入 QQ)

--------------------------------------------------
服务端口
--------------------------------------------------
- 127.0.0.1:3000: NapCat OneBot HTTP API，QCCA 用于获取登录信息和发送消息
- 127.0.0.1:40653: QQ Chat Exporter Web 页面和 API
- 127.0.0.1:40654: QQ Chat Exporter 与 NapCat 的桥接服务
- 127.0.0.1:40655: QCCA FastAPI 管理服务

QCCA 配置文件位置:
  %USERPROFILE%\.qq-chat-exporter\qcca\workspace\config.json

邮件回复发件 QQ 与邮箱授权码:
  在 QCCA 管理页面的“邮件回复”中配置。当前登录 QQ 会自动预留为一个发件账号，
  无需手动添加 QQ 号；其他发件 QQ 可手动新增并分别配置授权码。
  QCCA 使用当前选中的 QQ 邮箱回复消息发送者。
  授权码以明文 JSON 保存在
  %USERPROFILE%\.qq-chat-exporter\qcca\workspace\smtp.json，请妥善保护该文件；管理页面和 API 不会回显它。

管理页面不会直接创建 QQ 用户。QQ 用户、工作区和会话由 QCCA 在处理消息时自动写入配置文件。

QCCA 监听目录默认位置:
  %USERPROFILE%\Documents\QQChatExporter\live-capture
如需自定义，启动前设置环境变量 QCCA_WATCH_DIR。

--------------------------------------------------
系统要求
--------------------------------------------------
- 已安装的 QQNT (启动时会自动同步本机 QQNT 版本信息)
  下载地址: https://im.qq.com/
- Python 3.8+ (QCCA 模块需要)
  下载地址: https://www.python.org/
- ffmpeg (QCCA 语音识别需要，用于 amr 转 wav)
  下载地址: https://ffmpeg.org/
- 独立模式需要 Node.js 18+

--------------------------------------------------
常见问题
--------------------------------------------------
- 如果启动时提示 `Cannot find package 'express'`，通常是当前安装包文件损坏或缺失了。
  最简单的处理方式是重新下载官方完整包，完整解压后直接覆盖当前目录，再重新运行 `launcher-user.bat`。

- QCCA 依赖安装失败: 检查网络连接，确认能访问 pypi.tuna.tsinghua.edu.cn。
  也可手动执行: cd qcca && venv\Scripts\pip install -r requirements.txt

- QCCA 管理页面打不开: 确认 launcher-user.bat 已启动 QCCA API 窗口，并检查
  http://127.0.0.1:40655/docs 是否可以访问。40655 被占用时，可设置环境变量
  QCCA_API_PORT 后重新启动，并使用
  http://localhost:40653/qce/qcca/?apiPort=端口访问管理页面。

- 管理页面显示旧内容: 在浏览器强制刷新页面，并重启 QCCA API 服务使代码更新生效。

- 语音识别失败: 确认 ffmpeg 已安装并加入系统 PATH。
  QCCA 使用 ffmpeg 将 amr 转为 wav，再交由 FunASR 识别。

--------------------------------------------------
开源许可
--------------------------------------------------
本项目基于以下开源项目:
- NapCat (GPL-v3): https://github.com/NapNeko/NapCatQQ
- QQ Chat Exporter (GPL-v3): https://github.com/shuakami/qq-chat-exporter

本项目遵循 GNU General Public License v3 (GPL-v3) 协议。
https://www.gnu.org/licenses/gpl-3.0.html
完整许可证文件见本目录 LICENSE。
==================================================
