# QCCA-NapCat-QCE

> A Windows x64 bundle built on NapCatQQ and QQ Chat Exporter, with QCCA message processing and a local management page.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Platform: Windows x64](https://img.shields.io/badge/Platform-Windows%20x64-0078D4.svg)](#requirements)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](#requirements)

**Language:** [中文](README.md) | [English](README.en.md)

---

## Overview

| Component | Version / purpose |
| --- | --- |
| [NapCatQQ](https://github.com/NapNeko/NapCatQQ) | v4.18.19, QQ and OneBot interface |
| [QQ Chat Exporter](https://github.com/shuakami/qq-chat-exporter) | v5.5.80, export and browse QQ chat records |
| QCCA | v1.0.1; watches messages, invokes coding agents, and replies through QQ Mail |
| QCCA API | Local FastAPI management service |

## Features

- Export and browse QQ chat records.
- Receive NapCat live messages and write them to QCCA-managed `live-capture` JSONL files.
- Send text messages to a Codex Agent.
- Transcribe voice messages with FunASR before processing.
- Reply to message senders through QQ Mail SMTP.
- Manage workspace sandbox permissions and sender accounts from a local web page.

## Quick Start

1. Extract the full package anywhere.
2. In a release package, double-click `QCCA-NapCat-QCE.exe`; from a source checkout, run `launcher-user.bat`.
3. Sign in through the QQ client.
4. Open `http://localhost:40653/qce` and enter the console access token.
5. Open `http://localhost:40653/qce/qcca/` to manage QCCA.

In a release package, the launcher console remains visible during the first QR-code login and is hidden automatically after NapCat reports a valid QQ number. The QQ client window itself remains visible.

When the hidden launcher is running, QCCA shows an icon in the Windows notification area. Double-click it to open the management page, or right-click it to check status, stop QCCA, or exit QQ, NapCat, and QCCA.

Run `start-standalone.bat` to browse already exported records without signing in to QQ. Standalone mode does not start QCCA.

## QCCA Configuration

QCCA automatically creates and maintains QQ users, workspaces, and sessions while it processes messages. The management page can change sandbox permissions for existing workspaces, select the sender QQ, and store the QQ Mail authorization code for each sender.

The currently signed-in QQ is reserved automatically as an SMTP sender. SMTP authorization codes are stored in plaintext on this computer. Protect this file carefully:

```text
%USERPROFILE%\.qq-chat-exporter\qcca\workspace\smtp.json
```

The default watched directory is `%USERPROFILE%\Documents\QQChatExporter\live-capture`. Set `QCCA_WATCH_DIR` before launch to change it. Set `QCCA_API_PORT` to change the API port.

## Local Services

| Address / port | Purpose |
| --- | --- |
| `127.0.0.1:3000` | NapCat OneBot HTTP API used by QCCA |
| `127.0.0.1:40653` | QQ Chat Exporter web page and API |
| `127.0.0.1:40654` | QQ Chat Exporter and NapCat bridge |
| `127.0.0.1:40655` | Default QCCA FastAPI management service port |

## Requirements

- QQNT installed locally.
- Python 3.10 or later for QCCA.
- `ffmpeg` for AMR-to-WAV conversion.
- Node.js 18 or later for standalone mode only.

## Credits and License

- NapCat: [NapNeko/NapCatQQ](https://github.com/NapNeko/NapCatQQ)
- QQ Chat Exporter: [shuakami/qq-chat-exporter](https://github.com/shuakami/qq-chat-exporter)

This project preserves upstream attribution and is licensed under [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html). See [LICENSE](LICENSE) for the complete license.
