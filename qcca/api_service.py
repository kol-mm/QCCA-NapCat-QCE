import json
import os
import tempfile
from contextlib import suppress
from json import JSONDecodeError
from pathlib import Path
from threading import RLock
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config_service


app = FastAPI(
    title="QCCA API",
    description="QCCA 配置管理 API",
    version="1.0.0",
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

_config_lock = RLock()


class Workspace(BaseModel):
    sandbox: str = "read-only"
    sessions: Dict[str, str]


class User(BaseModel):
    workspaces: Dict[str, Workspace]
    recent_workspace_and_session: Dict[str, str]


def _config_path() -> Path:
    return Path(config_service.config_dir_file())


def _read_users() -> dict:
    try:
        with _config_lock, _config_path().open("r", encoding="utf-8") as file:
            data = json.load(file)
    except JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="QCCA 配置文件格式无效") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"无法读取 QCCA 配置：{exc}") from exc

    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="QCCA 配置根节点必须是对象")
    return data


def _write_users(users: dict) -> None:
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


@app.put("/qcca/config/update/{uid}")
def update_qcca_config(uid: int, user: User):
    with _config_lock:
        users = _read_users()
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
        _write_users(users)
    return True


@app.delete("/qcca/config/delete/{uid}")
def delete_qcca_config(uid: int):
    with _config_lock:
        users = _read_users()
        users.pop(str(uid), None)
        _write_users(users)
    return True
