import json
import os
import shutil
import socket
import sys
import tempfile
import time
from contextlib import suppress
from json import JSONDecodeError
from pathlib import Path
from threading import RLock
from typing import Any, Dict
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config_service


app = FastAPI(
    title="QCCA API",
    description="QCCA 配置管理 API",
    version="1.2.1",
    license_info={"name": "GPL-3.0"},
)
_qce_web_port = os.getenv("QCE_SERVER_PORT", "40653")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://127.0.0.1:{_qce_web_port}",
        f"http://localhost:{_qce_web_port}",
    ],
    allow_credentials=False,
    allow_methods=["GET", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health_check():
    """用于启动器和管理页面确认 API 已经完成启动。"""
    return {"status": "ok", "service": "qcca-api"}


@app.get("/qcca/audio-model-status")
def get_audio_model_status():
    """返回独立 Agent 上报的语音识别模型状态。"""
    return config_service.get_audio_model_status()


@app.get("/qcca/agent-status")
def get_agent_status():
    """Return whether QCCA Agent is idle or currently invoking an agent."""
    return config_service.get_agent_status()


@app.get("/qcca/records/{session_id}")
def get_session_records(session_id: str):
    """Return the JSONL chat records associated with one session UUID."""
    try:
        records = config_service.ReadMemory(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        'session_id': session_id,
        'total': len(records),
        'records': records[-200:],
    }

_config_lock = RLock()


class Workspace(BaseModel):
    sandbox: str = "read-only"
    sessions: Dict[str, Any]


class User(BaseModel):
    workspaces: Dict[str, Workspace]
    recent_workspace_and_session: Dict[str, str]


VALID_SANDBOXES = {"read-only", "workspace-write", "danger-full-access"}
VALID_AGENTS = {"codex", "claude"}


class SmtpConfigUpdate(BaseModel):
    sender_qq: str
    auth_code: str


class SetupConfigUpdate(BaseModel):
    default_agent: str = "codex"
    auth_code: str = ""


def _config_path() -> Path:
    return Path(config_service.config_dir_file())


def _read_users() -> dict:
    with config_service.user_config_file_lock():
        return _read_users_unlocked()


def _read_users_unlocked() -> dict:
    try:
        with _config_lock, _config_path().open("r", encoding="utf-8") as file:
            data = json.load(file)
    except JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="QCCA 配置文件格式无效") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"无法读取 QCCA 配置：{exc}") from exc

    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="QCCA 配置根节点必须是对象")
    if config_service.migrate_user_config(data):
        _write_users_unlocked(data)
    return data


def _write_users(users: dict) -> None:
    with config_service.user_config_file_lock():
        _write_users_unlocked(users)


def _write_users_unlocked(users: dict) -> None:
    config_path = _config_path()
    temporary_path = None
    try:
        with _config_lock, tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(users, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, config_path)
    except OSError as exc:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink()
        raise HTTPException(status_code=500, detail=f"无法写入 QCCA 配置：{exc}") from exc


def _model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _get_current_login_qq() -> str | None:
    try:
        with urlopen("http://127.0.0.1:3000/get_login_info", timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
        qq = data.get("data", {}).get("user_id")
        return str(qq) if isinstance(qq, (str, int)) and str(qq).isdigit() else None
    except (URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def _smtp_response() -> dict:
    login_qq = _get_current_login_qq()
    try:
        config = (
            config_service.ensure_smtp_account(login_qq)
            if login_qq else config_service.get_smtp_config()
        )
    except (OSError, config_service.SmtpConfigError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    accounts = config.get("accounts", {})
    ordered_qqs = sorted(accounts, key=lambda qq: (qq != login_qq, qq))
    selected = config.get("selected_sender_qq")
    return {
        "login_qq": login_qq,
        "selected_sender_qq": selected,
        "configured": bool(accounts.get(selected, {}).get("auth_code")),
        "accounts": [
            {"qq": qq, "configured": bool(accounts[qq].get("auth_code"))}
            for qq in ordered_qqs
        ],
    }


def _port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.8):
            return True
    except OSError:
        return False


def _service(service_id: str, name: str, status: str, summary: str,
             action: str = "", required: bool = True) -> dict:
    return {
        "id": service_id,
        "name": name,
        "status": status,
        "summary": summary,
        "action": action,
        "required": required,
    }


def _system_status() -> dict:
    try:
        preferences = config_service.get_preferences()
    except config_service.PreferencesConfigError:
        preferences = {"setup_completed": False, "default_agent": "codex"}
    default_agent = preferences["default_agent"]
    login_qq = _get_current_login_qq()
    napcat_open = _port_is_open(3000)
    try:
        qce_port = int(_qce_web_port)
    except ValueError:
        qce_port = 40653

    services = []
    if login_qq:
        services.append(_service("napcat", "QQ 与 NapCat", "ready", f"QQ {login_qq} 已登录"))
    elif napcat_open:
        services.append(_service("napcat", "QQ 与 NapCat", "waiting", "服务已启动，等待 QQ 登录", "请完成扫码或快速登录"))
    else:
        services.append(_service("napcat", "QQ 与 NapCat", "error", "尚未连接到 QQ", "请从 QCCA 启动器启动并登录 QQ"))

    if _port_is_open(qce_port):
        services.append(_service("qce", "QQ Chat Exporter", "ready", "聊天数据服务运行正常"))
    else:
        services.append(_service("qce", "QQ Chat Exporter", "error", "聊天数据服务未启动", "请重新启动完整程序"))
    services.append(_service("qcca-api", "QCCA 管理服务", "ready", "管理接口运行正常"))

    agent_status = config_service.get_agent_status()
    agent_value = agent_status.get("status", "unknown")
    active_agent = agent_status.get("agent") or default_agent
    agent_cli = shutil.which(active_agent)
    if not agent_cli:
        services.append(_service("agent", "AI Agent", "error", f"未找到 {active_agent} 命令", f"请安装并登录 {active_agent}"))
    elif agent_value in {"idle", "running"}:
        summary = f"{active_agent} 正在处理任务" if agent_value == "running" else f"{active_agent} 已就绪"
        services.append(_service("agent", "AI Agent", "ready", summary))
    elif agent_value in {"not_started", "stopped"}:
        services.append(_service("agent", "AI Agent", "error", "QCCA Agent 未运行", "请重新启动 QCCA 服务"))
    elif agent_value == "failed":
        services.append(_service("agent", "AI Agent", "error", "最近一次 Agent 调用失败", "请检查 Agent 登录和网络"))
    else:
        services.append(_service("agent", "AI Agent", "waiting", "正在确认 Agent 状态"))

    audio_status = config_service.get_audio_model_status()
    audio_value = audio_status.get("status", "unknown")
    if audio_value == "ready":
        services.append(_service("audio", "语音识别", "ready", "音频模型已加载", required=False))
    elif audio_value == "loading":
        services.append(_service("audio", "语音识别", "waiting", "首次加载音频模型", "文字消息不受影响", required=False))
    elif audio_value in {"failed", "stopped"}:
        services.append(_service("audio", "语音识别", "warning", "语音识别当前不可用", audio_status.get("message", "请查看 Agent 日志"), required=False))
    else:
        services.append(_service("audio", "语音识别", "waiting", "等待音频模型状态", "文字消息不受影响", required=False))

    try:
        smtp = _smtp_response()
        if smtp["configured"]:
            services.append(_service("smtp", "QQ 邮箱回复", "ready", f"发件账号 {smtp['selected_sender_qq']} 已配置", required=False))
        else:
            services.append(_service("smtp", "QQ 邮箱回复", "warning", "尚未配置邮箱授权码", "需要邮件回复时再配置", required=False))
    except HTTPException as exc:
        services.append(_service("smtp", "QQ 邮箱回复", "warning", "邮箱配置无法读取", str(exc.detail), required=False))

    python_ready = sys.version_info >= (3, 10)
    services.append(_service(
        "python", "Python 环境", "ready" if python_ready else "error",
        f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "请安装 Python 3.10 或更高版本" if not python_ready else "",
    ))
    ffmpeg_path = shutil.which("ffmpeg")
    services.append(_service(
        "ffmpeg", "FFmpeg", "ready" if ffmpeg_path else "warning",
        "语音转换工具已安装" if ffmpeg_path else "未找到 FFmpeg",
        "仅使用文字消息时可以暂不安装" if not ffmpeg_path else "",
        required=False,
    ))

    required_error = any(item["required"] and item["status"] == "error" for item in services)
    needs_attention = any(item["status"] in {"waiting", "warning", "error"} for item in services)
    overall = "error" if required_error else ("attention" if needs_attention else "ready")
    return {
        "overall": overall,
        "checked_at": time.time(),
        "default_agent": default_agent,
        "setup_completed": preferences["setup_completed"],
        "services": services,
    }


@app.get("/qcca/system-status")
def get_system_status():
    """Return one friendly status list for the management page."""
    return _system_status()


@app.get("/qcca/setup")
def get_setup_config():
    try:
        preferences = config_service.get_preferences()
        smtp = _smtp_response()
    except (OSError, config_service.PreferencesConfigError, config_service.SmtpConfigError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        **preferences,
        "login_qq": smtp["login_qq"],
        "smtp_configured": smtp["configured"],
        "agents": [
            {"name": name, "installed": shutil.which(name) is not None}
            for name in sorted(VALID_AGENTS)
        ],
    }


@app.put("/qcca/setup")
def update_setup_config(config: SetupConfigUpdate):
    default_agent = config.default_agent.strip().lower()
    if default_agent not in VALID_AGENTS:
        raise HTTPException(status_code=400, detail="默认 Agent 无效，可选：codex、claude")
    auth_code = config.auth_code.strip()
    login_qq = _get_current_login_qq()
    if auth_code and not login_qq:
        raise HTTPException(status_code=409, detail="当前 QQ 尚未登录，暂时无法保存邮箱授权码")
    try:
        if auth_code:
            config_service.save_smtp_config(login_qq, auth_code)
        preferences = config_service.save_preferences(default_agent, setup_completed=True)
    except (OSError, ValueError, config_service.SmtpConfigError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        **preferences,
        "login_qq": login_qq,
        "smtp_configured": _smtp_response()["configured"],
    }


@app.get("/qcca/configs")
def get_qcca_configs():
    return _read_users()


@app.get("/qcca/config/{uid}")
def get_qcca_config(uid: int):
    users = _read_users()
    user = users.get(str(uid))
    if user is None:
        raise HTTPException(status_code=404, detail="QQ 用户配置不存在")
    return user


@app.get("/qcca/smtp-config")
def get_smtp_config():
    """仅返回配置状态，授权码绝不通过接口回传。"""
    return _smtp_response()


@app.put("/qcca/smtp-config")
def update_smtp_config(config: SmtpConfigUpdate):
    sender_qq = config.sender_qq.strip()
    auth_code = config.auth_code.strip()
    if not sender_qq.isdigit() or not 5 <= len(sender_qq) <= 12:
        raise HTTPException(status_code=400, detail="发件 QQ 号格式无效")
    if not auth_code:
        raise HTTPException(status_code=400, detail="QQ 邮箱授权码不能为空")
    try:
        config_service.save_smtp_config(sender_qq, auth_code)
    except (OSError, config_service.SmtpConfigError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _smtp_response()


@app.put("/qcca/smtp-config/select/{sender_qq}")
def select_smtp_config(sender_qq: str):
    try:
        if not config_service.select_smtp_account(sender_qq):
            raise HTTPException(status_code=404, detail="发件 QQ 配置不存在")
    except (OSError, config_service.SmtpConfigError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _smtp_response()


@app.delete("/qcca/smtp-config/{sender_qq}")
def delete_smtp_config(sender_qq: str):
    login_qq = _get_current_login_qq()
    if login_qq is None:
        raise HTTPException(status_code=503, detail="NapCat 登录接口不可用，暂时禁止删除发件 QQ 配置")
    if sender_qq == login_qq:
        raise HTTPException(status_code=400, detail="当前登录 QQ 的预留配置不能删除")
    try:
        if not config_service.delete_smtp_account(sender_qq):
            raise HTTPException(status_code=404, detail="发件 QQ 配置不存在")
    except (OSError, config_service.SmtpConfigError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _smtp_response()


@app.put("/qcca/config/update/{uid}")
def update_qcca_config(uid: int, user: User):
    with _config_lock, config_service.user_config_file_lock():
        users = _read_users_unlocked()
        if str(uid) not in users:
            raise HTTPException(status_code=404, detail="QQ 用户配置不存在")
        updated = _model_to_dict(user)
        current = users[str(uid)]
        current_workspaces = current.get("workspaces", {})
        updated_workspaces = updated.get("workspaces", {})
        if set(current_workspaces) != set(updated_workspaces):
            raise HTTPException(status_code=400, detail="工作目录由 QCCA 自动管理，不能修改")
        for workspace_name, current_workspace in current_workspaces.items():
            updated_workspace = updated_workspaces.get(workspace_name)
            if not isinstance(updated_workspace, dict):
                raise HTTPException(status_code=400, detail="工作区配置格式无效")
            if updated_workspace.get("sandbox") not in VALID_SANDBOXES:
                raise HTTPException(status_code=400, detail="沙箱权限值无效")
            current_sessions = current_workspace.get("sessions", {})
            updated_sessions = updated_workspace.get("sessions", {})
            if not isinstance(current_sessions, dict) or not isinstance(updated_sessions, dict):
                raise HTTPException(status_code=400, detail="会话配置格式无效")
            if set(current_sessions) != set(updated_sessions):
                raise HTTPException(status_code=400, detail="会话名称由 QCCA 自动管理，不能修改")
            # Session names and IDs remain immutable.  Agent type is the only
            # session field exposed for management-page editing.
            normalized_sessions = {}
            for session_name, current_session in current_sessions.items():
                submitted = updated_sessions[session_name]
                if not isinstance(current_session, dict) or not isinstance(submitted, dict):
                    raise HTTPException(status_code=400, detail="会话配置格式无效")
                if submitted.get("id") != current_session.get("id"):
                    raise HTTPException(status_code=400, detail="会话 ID 由 QCCA 自动管理，不能修改")
                agent = submitted.get("agent", current_session.get("agent", "codex"))
                if not isinstance(agent, str) or agent.lower() not in VALID_AGENTS:
                    raise HTTPException(status_code=400, detail="Agent 类型无效，可选：codex、claude")
                normalized_sessions[session_name] = {
                    **current_session,
                    "agent": agent.lower(),
                }
            updated_workspace["sessions"] = normalized_sessions
        recent = updated.get("recent_workspace_and_session", {})
        if len(recent) > 1:
            raise HTTPException(status_code=400, detail="最近工作区和会话只能有一组")
        has_sessions = any(
            bool(workspace.get("sessions"))
            for workspace in updated_workspaces.values()
        )
        if has_sessions and not recent:
            raise HTTPException(status_code=400, detail="至少选择一个最近会话")
        for workspace_name, session_name in recent.items():
            workspace_data = updated_workspaces.get(workspace_name)
            if workspace_data is None or session_name not in workspace_data.get("sessions", {}):
                raise HTTPException(status_code=400, detail="最近工作区或会话不存在")
        users[str(uid)] = updated
        _write_users_unlocked(users)
    return True


@app.delete("/qcca/config/delete/{uid}")
def delete_qcca_config(uid: int):
    with _config_lock, config_service.user_config_file_lock():
        users = _read_users_unlocked()
        users.pop(str(uid), None)
        _write_users_unlocked(users)
    return True
