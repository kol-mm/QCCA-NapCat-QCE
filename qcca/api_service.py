import json
import os
import tempfile
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
    version="1.1.0",
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


class SmtpConfigUpdate(BaseModel):
    sender_qq: str
    auth_code: str


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
            if current_workspace.get("sessions", {}) != updated_workspaces[workspace_name].get("sessions", {}):
                raise HTTPException(status_code=400, detail="会话由 QCCA 自动管理，不能修改")
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
