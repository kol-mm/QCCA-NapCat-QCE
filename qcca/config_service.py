import os
import json
import re
import time
import tempfile
from threading import RLock
from typing import Optional

_smtp_lock = RLock()


class SmtpConfigError(RuntimeError):
    """SMTP 配置无法安全读取时抛出，防止后续写入覆盖原文件。"""


def parse_sandbox_params(text: str) -> dict[str, str | None]:
    result = {"workspace": None, "sandbox": None, "session": None}

    if not text.startswith("/"):
        return result
    if text.count('"') % 2:
        return result

    pattern = re.compile(r'(workspace|session|sandbox)=(?:"([^"]*)"|(\S+))')
    for match in pattern.finditer(text[1:]):
        key = match.group(1)
        value = match.group(2) if match.group(2) is not None else match.group(3)
        if key == "workspace":
            result["workspace"] = value
        elif key == "session":
            result["session"] = value
        elif key == "sandbox" and value in {
            "read-only", "workspace-write", "danger-full-access",
        }:
            result["sandbox"] = value

    return result

def is_sandbox_command(text: str) -> bool:
    """仅把包含切换参数的斜杠消息视为分支切换命令。"""
    if not text.startswith('/'):
        return False
    return any(f'{key}=' in text[1:] for key in ('workspace', 'session', 'sandbox'))
def get_dict_user(workspace,session,resume,sandbox='read-only',):
    dict_user={}
    dict_workspaces={}
    dict_workspace={}
    dict_sessions={}
    dict_recent_session={}

    dict_sessions[session]=resume
    dict_workspace['sandbox']=sandbox
    dict_workspace['sessions']=dict_sessions
    dict_workspaces[workspace]=dict_workspace
    dict_user['workspaces']=dict_workspaces
    dict_recent_session[workspace]=session
    dict_user['recent_workspace_and_session']=dict_recent_session

    return dict_user
def get_dict_workspace(session,resume,sandbox='read-only'):
    dict_workspace={}
    dict_sessions={}
    dict_workspace['sandbox']=sandbox
    dict_sessions[session]=resume
    dict_workspace['sessions']=dict_sessions
    return dict_workspace

def config_dir_file():
    work_path = os.path.expanduser(r'~\.qq-chat-exporter\qcca')
    config_dir = os.path.join(work_path, "workspace")
    config_file = os.path.join(config_dir, "config.json")
    os.makedirs(config_dir, exist_ok=True)
    if not os.path.exists(config_file) or os.path.getsize(config_file) == 0:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
    return config_file


def smtp_config_file() -> str:
    """返回接收端 QQ 邮箱 SMTP 配置文件的本机路径。"""
    config_dir = os.path.dirname(config_dir_file())
    return os.path.join(config_dir, "smtp.json")


def audio_model_status_file() -> str:
    """返回 Agent 写入的音频模型状态文件路径。"""
    return os.path.join(os.path.dirname(config_dir_file()), "audio_model_status.json")


def update_audio_model_status(status: str, message: str = "") -> None:
    """原子写入音频模型状态，供独立运行的 API 读取。"""
    path = audio_model_status_file()
    payload = {
        "status": status,
        "message": message,
        "updated_at": time.time(),
    }
    fd, temporary_path = tempfile.mkstemp(
        prefix=".audio_model_status.", suffix=".tmp", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    except OSError:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def get_audio_model_status() -> dict:
    """读取 Agent 状态；就绪状态超过 15 秒未心跳则视为已停止。"""
    try:
        with open(audio_model_status_file(), "r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return {"status": "not_started", "message": "Agent 尚未上报音频模型状态"}
    except (OSError, json.JSONDecodeError):
        return {"status": "unknown", "message": "无法读取音频模型状态"}

    status = data.get("status")
    updated_at = data.get("updated_at")
    if not isinstance(status, str) or not isinstance(updated_at, (int, float)):
        return {"status": "unknown", "message": "音频模型状态格式无效"}
    if status == "ready" and time.time() - updated_at > 15:
        return {"status": "stopped", "message": "Agent 心跳已停止"}
    return {
        "status": status,
        "message": data.get("message") if isinstance(data.get("message"), str) else "",
        "updated_at": updated_at,
    }


def _normalize_smtp_config(data: object) -> dict:
    """兼容旧版单账号 SMTP 配置，统一为多账号结构。"""
    result = {"accounts": {}, "selected_sender_qq": None}
    if not isinstance(data, dict):
        return result

    accounts = data.get("accounts")
    if isinstance(accounts, dict):
        for qq, account in accounts.items():
            if isinstance(qq, str) and qq.isdigit() and isinstance(account, dict):
                auth_code = account.get("auth_code", "")
                result["accounts"][qq] = {
                    "auth_code": auth_code.strip() if isinstance(auth_code, str) else ""
                }
        selected = data.get("selected_sender_qq")
        if selected in result["accounts"]:
            result["selected_sender_qq"] = selected
        return result

    # 兼容此前的 {sender_qq, auth_code} 文件。
    sender_qq = data.get("sender_qq")
    auth_code = data.get("auth_code", "")
    if isinstance(sender_qq, str) and sender_qq.isdigit():
        result["accounts"][sender_qq] = {
            "auth_code": auth_code.strip() if isinstance(auth_code, str) else ""
        }
        result["selected_sender_qq"] = sender_qq
    elif isinstance(auth_code, str) and auth_code:
        result["_legacy_auth_code"] = auth_code
    return result


def get_smtp_config() -> dict:
    """读取本机 SMTP 多账号配置。"""
    try:
        with _smtp_lock, open(smtp_config_file(), "r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return {"accounts": {}, "selected_sender_qq": None}
    except json.JSONDecodeError as exc:
        raise SmtpConfigError("SMTP 配置文件格式无效，请修复或移走 smtp.json 后重试") from exc
    except OSError as exc:
        raise SmtpConfigError(f"无法读取 SMTP 配置文件：{exc}") from exc
    if not isinstance(data, dict):
        raise SmtpConfigError("SMTP 配置文件根节点必须是 JSON 对象")
    return _normalize_smtp_config(data)


def save_smtp_config(sender_qq: str, auth_code: str) -> None:
    """新增或更新 SMTP 发件 QQ，并将其设为当前发件账号。"""
    with _smtp_lock:
        config = get_smtp_config()
        config["accounts"][sender_qq.strip()] = {"auth_code": auth_code.strip()}
        config["selected_sender_qq"] = sender_qq.strip()
        _write_smtp_config(config)


def ensure_smtp_account(sender_qq: str) -> dict:
    """为当前登录 QQ 预留账号配置；不会覆盖已有选择或授权码。"""
    with _smtp_lock:
        config = get_smtp_config()
        changed = False
        if sender_qq not in config["accounts"]:
            config["accounts"][sender_qq] = {"auth_code": config.pop("_legacy_auth_code", "")}
            changed = True
        if not config["selected_sender_qq"]:
            config["selected_sender_qq"] = sender_qq
            changed = True
        if changed:
            _write_smtp_config(config)
        return config


def select_smtp_account(sender_qq: str) -> bool:
    with _smtp_lock:
        config = get_smtp_config()
        if sender_qq not in config["accounts"]:
            return False
        config["selected_sender_qq"] = sender_qq
        _write_smtp_config(config)
        return True


def delete_smtp_account(sender_qq: str) -> bool:
    with _smtp_lock:
        config = get_smtp_config()
        if sender_qq not in config["accounts"]:
            return False
        del config["accounts"][sender_qq]
        if config.get("selected_sender_qq") == sender_qq:
            config["selected_sender_qq"] = next(iter(config["accounts"]), None)
        _write_smtp_config(config)
        return True


def _write_smtp_config(config: dict) -> None:
    path = smtp_config_file()
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        safe = dict(config)
        safe["accounts"] = {
            qq: {"auth_code": account.get("auth_code", "")}
            for qq, account in config.get("accounts", {}).items()
        }
        safe.pop("_legacy_auth_code", None)
        json.dump(safe, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)
def dict_user_exist(uid):
    try:
        with open(config_dir_file(), 'r', encoding='utf-8') as f:
            config_dict = json.load(f)
            if not uid in config_dict:
                return None
            else:
                return config_dict[uid]
    except (FileNotFoundError,json.JSONDecodeError,PermissionError,OSError) as e:
        return None
def is_user_workspace_or_session(user,workspace,session):
    if isinstance(user, dict):
        try:
            if workspace in user['workspaces'] and session in user['workspaces'][workspace]['sessions']:
                return True
        except (KeyError, TypeError):
            pass
    return False
def add_user_data(config_dict,config_path,uid, workspace, session, resume, sandbox='read-only'):
    sandbox = sandbox or 'read-only'
    if uid not in config_dict:
        config_dict[uid] = get_dict_user(workspace, session, resume, sandbox)
    else:
        try:
            user_workspaces = config_dict[uid]['workspaces']
            if workspace in user_workspaces:
                if session in user_workspaces[workspace]['sessions']:
                    print('已存在')
                    return False
                user_workspaces[workspace]['sessions'][session] = resume
            else:
                user_workspaces[workspace] = get_dict_workspace(session, resume, sandbox)
        except (KeyError, TypeError) as e:
            print(f'出现错误，键缺失: {e}')
            return False

    try:
        # 内存更新最近会话
        config_dict[uid]["recent_workspace_and_session"].clear()
        config_dict[uid]["recent_workspace_and_session"][workspace] = session
        # 一次性写磁盘
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, ensure_ascii=False, indent=2)
        return True
    except (KeyError, FileNotFoundError, json.JSONDecodeError, PermissionError, OSError) as e:
        print(f'出现错误{e}')
        return False

def get_user_recent_session(user:Optional[dict]):
    if isinstance(user, dict):
        try:
            user_workspaces = user['workspaces']
            recent_workspace_and_session = user['recent_workspace_and_session']
            workspace, session = next(iter(recent_workspace_and_session.items()))
            resume = user_workspaces[workspace]['sessions'][session]
            return workspace, resume
        except (KeyError, StopIteration, TypeError) as e:
            print(e)
            return None, None
    print('用户不存在')
    return None, None

def set_user_recent_session(config_dict, config_path, uid, workspace, session):
    """将指定工作区和会话设为用户下次使用的分支。"""
    try:
        config_dict[uid]["recent_workspace_and_session"] = {workspace: session}
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, ensure_ascii=False, indent=2)
        return True
    except (KeyError, FileNotFoundError, PermissionError, OSError, TypeError) as e:
        print(f'更新最近分支失败: {e}')
        return False
def refresh_and_add_user_data(uid, workspace, session, resume, sandbox='read-only'):
    config_dict = {}
    config_path = config_dir_file()
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config_dict = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError, TypeError) as e:
        print(f'出现错误{e}')
        return False

    user = config_dict.get(uid)
    if is_user_workspace_or_session(user, workspace, session):
        # 会话已存在，仅切换recent，写回
        try:
            config_dict[uid]["recent_workspace_and_session"].clear()
            config_dict[uid]["recent_workspace_and_session"][workspace] = session
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, ensure_ascii=False, indent=2)
            print('切换成功')
            return True
        except (KeyError, FileNotFoundError, PermissionError, OSError, TypeError) as e:
            print(f'写入失败 {e}')
            return False
    else:
        # 把内存字典和路径直接传进去，不再重新读文件
        if add_user_data(config_dict, config_path, uid, workspace, session, resume, sandbox):
            print('新增切换成功')
            return True
        else:
            print('新增失败')
            return False
def get_receive_uid():
    path = os.getcwd()
    path_father = os.path.dirname(path)
    path_config = os.path.join(path_father, 'config')
    if not os.path.isdir(path_config):
        return None
    path_list = os.listdir(path_config)
    pattern = re.compile(r'^napcat_(\d+)\.json$')
    for path in path_list:
        match = pattern.match(path)
        if match:
            uid = match.group(1)
            print(uid)
            return uid
    return None

# def refresh_and_add_user_data(uid, workspace, session, resume, sandbox='read-only'):
#     config_dict = {}
#     config_path = config_dir_file()
#     try:
#         with open(config_path, 'r', encoding='utf-8') as f:
#             config_dict = json.load(f)
#         if is_user_workspace_or_session(config_dict.get(uid), workspace, session):
#             config_dict[uid]["recent_workspace_and_session"].clear()
#             config_dict[uid]["recent_workspace_and_session"][workspace] = session
#             print('切换成功')
#             with open(config_path, 'w', encoding='utf-8') as f:
#                 json.dump(config_dict, f, ensure_ascii=False, indent=2)
#             return True
#         else:
#             if add_user_data(config_dict,config_path,uid, workspace, session, resume, sandbox):
#                 print('新增切换成功')
#                 return True
#             else:
#                 print('新增失败')
#                 return False
#     except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError) as e:
#         print(f'出现错误{e}')
#         return False
#废弃
# def refresh_user_session(uid,workspace,session):
#     user=dict_user_exist(uid)
#     if user :
#         try:
#             if workspace in user['recent_workspace_and_session']:
#                 print('已经是这个会话')
#                 return False
#             else:
#                 if session in user['workspaces'][workspace]['sessions']:
#                     user['recent_workspace_and_session'][workspace]=session
#                     with open(config_dir_file(), 'w', encoding='utf-8') as f:
#                         json.dump(user, f, ensure_ascii=False, indent=2)
#                         return True
#         except (KeyError,StopIteration,FileNotFoundError,json.JSONDecodeError,PermissionError,OSError) as e:
#优化合并
# def dict_user_workspace_or_session(user,workspace,session):
#     user=dict_user_exist(user)
#     if(user):
#         try:
#             user_workspaces = user['workspaces']
#             if workspace in user_workspaces:
#                 if session in user_workspaces[workspace]['sessions']:
#                     return user
#                 else:
#                     return None
#             else:
#                 return None
#         except (KeyError,StopIteration) as e:
#             print(e)
#             return None
# def save_user_data():
#     pass
# def add_user_data(uid,workspace,session,resume,sandbox='read-only'):
#     config_dict = {}
#     config_path=config_dir_file()
#     try:
#         with open(config_path, 'r', encoding='utf-8') as f:
#             config_dict = json.load(f)
#     except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError) as e:
#         print(f'配置有问题{e}')
#         return False
#     if not config_dict.get(uid):
#         try:
#             config_dict[uid] = get_dict_user(workspace, session, resume, sandbox)
#
#         except (json.JSONDecodeError,PermissionError,OSError)  as e:
#             return False
#     else:
#         try:
#             user_workspaces = config_dict[uid]['workspaces']
#             if workspace in user_workspaces:
#                 if session in user_workspaces[workspace]['sessions']:
#                     print('已存在')
#                     return False
#                 else:
#                     user_workspaces[workspace]['sessions'][session] = resume
#             else:
#                 user_workspaces[workspace] =get_dict_workspace(session,resume,sandbox)
#         except (FileNotFoundError,json.JSONDecodeError,PermissionError,OSError) as e:
#             print('出现错误')
#             return False
#     try:
#         config_dict[uid]["recent_workspace_and_session"].clear()
#         config_dict[uid]["recent_workspace_and_session"][workspace] = session
#         with open(config_path, 'w', encoding='utf-8') as f:
#             json.dump(config_dict, f, ensure_ascii=False, indent=2)
#             return True
#     except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError) as e:
#         print(f'出现错误{e}')
#         return False






