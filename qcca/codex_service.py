import os.path
import subprocess
import json
from typing import Optional
import config_service as config
import time
import uuid
from pathlib import Path
def codex_control(
    context: str,
    workspace: str,
    resume: Optional[str] = None,
    sandbox: str = "read-only",
):
    if not context or not context.strip():
        raise ValueError("context 不能为空")

    if not workspace:
        raise ValueError("workspace 不能为空")

    sandbox = sandbox or "read-only"

    if not Path(workspace).is_dir():
        raise ValueError(f"workspace 不存在或不是目录: {workspace}")

    cmd_list = [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "-C",
        workspace,
        "--sandbox",
        sandbox,
        context,
    ]

    if resume:
        cmd_list.extend(["resume", resume])

    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError("未找到 codex 命令，请确认已安装并已加入 PATH") from e
    except subprocess.TimeoutExpired as e:
        raise TimeoutError("Codex 执行超时，超过 300 秒") from e
    except OSError as e:
        raise RuntimeError(f"Codex 启动失败: {e}") from e

    if result.returncode != 0:
        error_message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"Codex 执行失败，退出码: {result.returncode}"
            + (f"\n{error_message}" if error_message else "")
        )

    stdout_list = result.stdout
    out_list = []
    error_list = []

    for line in stdout_list.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            line_json = json.loads(line)
        except json.JSONDecodeError:
            error_list.append(f"无法解析 JSON: {line[:200]}")
            continue

        if not isinstance(line_json, dict):
            continue

        if line_json.get("type") == "thread.started":
            thread_id = line_json.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                resume = thread_id

        elif line_json.get("type") in {"error", "thread.error"}:
            error_list.append(
                str(line_json.get("message") or line_json.get("error") or line_json)
            )

        elif line_json.get("type") == "item.completed":
            item = line_json.get("item")
            if not isinstance(item, dict):
                continue

            if item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str) and text:
                    out_list.append(text)
                    print(text)

    if error_list and not out_list:
        raise RuntimeError("\n".join(error_list))

    return "\n".join(out_list), resume
# def codex_control(context:str,workspace:str,resume:Optional[str]=None,sandbox:str='read-only'):
#     cmd_list=['codex','exec','--json','--skip-git-repo-check','-C',workspace,'--sandbox',sandbox,context]
#     if resume:
#         cmd_list.extend(['resume',resume])
#     stdout_list=subprocess.run(
#         cmd_list,
#         capture_output=True,
#         encoding="utf-8"
#     ).stdout
#     out_list=[]
#     for line in stdout_list.split('\n'):
#         if line.strip() == '':
#             continue
#         try:
#             line_json = json.loads(line.strip())
#         except json.JSONDecodeError as e:
#             continue
#         if line_json.get('type') =='thread.started':
#              resume=line_json.get('thread_id')
#         if line_json.get('type') == 'item.completed':
#             if line_json.get('item').get('type')== 'agent_message':
#                 out_list.append(line_json.get('item').get('text'))
#                 print(line_json.get('item').get('text'))
#     return '\n'.join(out_list),resume
def codex_run(uid,context:str,workspace:Optional[str]=None,session:Optional[str]=None,sandbox:str=None):
    config_path=config.config_dir_file()
    config_dict = {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()

        if content:
            config_dict = json.loads(content)
        else:
            config_dict = {}
        user = config_dict.get(uid)
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError) as e:
        return f'抱歉出现了一些错误:{e}'
    try:
        if user:
            recent_workspace, recent_resume = config.get_user_recent_session(user)
            if not recent_workspace:
                return '出现错误:最近工作空间或会话配置无效'
            recent_sandbox = user['workspaces'][recent_workspace]['sandbox']
            recent_sandbox = recent_sandbox or 'read-only'
            user['workspaces'][recent_workspace]['sandbox'] = recent_sandbox
            if not session:
                if workspace == recent_workspace or not workspace:
                    session = user['recent_workspace_and_session'].get(recent_workspace)
                    user['workspaces'][recent_workspace]['sandbox'] = sandbox if sandbox else recent_sandbox
                    codex_answer, resume = codex_control(context, recent_workspace, recent_resume,
                                                         user['workspaces'][recent_workspace]['sandbox'])
                    user['workspaces'][recent_workspace]['sessions'][session] = resume
                    with open(config_path, 'w', encoding='utf-8') as f:
                        json.dump(config_dict, f, ensure_ascii=False, indent=2)
                    return f'工作空间:{recent_workspace},会话:{session}\n' + codex_answer.strip()
                else:
                    if workspace in user['workspaces']:
                        user['workspaces'][workspace]['sandbox'] = sandbox or \
                            user['workspaces'][workspace]['sandbox'] or 'read-only'
                        codex_answer, resume = codex_control(context, workspace, None,
                                                             user['workspaces'][workspace]['sandbox'])
                        session = uuid.uuid4().hex[:12]
                        config.add_user_data(config_dict, config_path, uid, workspace, session, resume,
                                             user['workspaces'][workspace]['sandbox'])
                        return f'工作空间:{workspace},会话:{session}\n' + codex_answer.strip()
                    else:
                        codex_answer, resume = codex_control(context, workspace, None, sandbox or 'read-only')
                        session = uuid.uuid4().hex[:12]
                        config.add_user_data(config_dict, config_path, uid, workspace, session, resume, sandbox or 'read-only')
                        return f'工作空间:{workspace},会话:{session}\n' + codex_answer.strip()
            else:
                if workspace == recent_workspace or not workspace:
                    if session in user['workspaces'][recent_workspace]['sessions']:
                        resume = user['workspaces'][recent_workspace]['sessions'][session]
                        user['workspaces'][recent_workspace]['sandbox'] = sandbox if sandbox else recent_sandbox
                        codex_answer, resume = codex_control(context, recent_workspace, resume,
                                                             user['workspaces'][recent_workspace]['sandbox'])
                        user['workspaces'][recent_workspace]['sessions'][session] = resume
                        config.set_user_recent_session(config_dict, config_path, uid, recent_workspace, session)
                        return f'工作空间:{recent_workspace},会话:{session}\n' + codex_answer.strip()
                    else:
                        codex_answer, resume = codex_control(context, recent_workspace, None,
                                                             user['workspaces'][recent_workspace]['sandbox'])
                        config.add_user_data(config_dict, config_path, uid, recent_workspace, session, resume,
                                             user['workspaces'][recent_workspace]['sandbox'])
                        return f'工作空间:{recent_workspace},会话:{session}\n' + codex_answer.strip()
                else:
                    if workspace in user['workspaces']:
                        user['workspaces'][workspace]['sandbox'] = sandbox or \
                            user['workspaces'][workspace]['sandbox'] or 'read-only'
                        if session in user['workspaces'][workspace]['sessions']:

                            codex_answer, resume = codex_control(context, workspace,
                                                                 user['workspaces'][workspace]['sessions'][session],
                                                                 user['workspaces'][workspace]['sandbox'])
                            user['workspaces'][workspace]['sessions'][session] = resume
                            config.set_user_recent_session(config_dict, config_path, uid, workspace, session)
                            return f'工作空间:{workspace},会话:{session}\n' + codex_answer.strip()
                        else:
                            codex_answer, resume = codex_control(context, workspace, None,
                                                                 user['workspaces'][workspace]['sandbox'])
                            config.add_user_data(config_dict, config_path, uid, workspace, session, resume,
                                                 user['workspaces'][workspace]['sandbox'])
                            return f'工作空间:{workspace},会话:{session}\n' + codex_answer.strip()
                    else:
                        codex_answer, resume = codex_control(context, workspace, None, sandbox or 'read-only')
                        session = session or uuid.uuid4().hex[:12]
                        config.add_user_data(config_dict, config_path, uid, workspace, session, resume, sandbox or 'read-only')
                        return f'工作空间:{workspace},会话:{session}\n' + codex_answer.strip()
        else:
            print('新用户')

            workspace=workspace or os.path.expanduser(rf'~\.qq-chat-exporter\qcca\workspace\{int(time.time()*1000)}')
            os.makedirs(workspace, exist_ok=True)
            session=session or uuid.uuid4().hex[:12]
            codex_answer, resume = codex_control(context, workspace, None, sandbox or 'read-only')
            if config.add_user_data(config_dict, config_path, uid, workspace, session, resume, sandbox or 'read-only'):
                return f'创建新用户成功,工作空间:{workspace},会话:{session}\n' + codex_answer.strip()
            else:
                return '创建新用户失败\n' + codex_answer.strip()
    except (FileNotFoundError, PermissionError, OSError, KeyError, TypeError, json.JSONDecodeError) as e:
        print(e)
        return f'出现错误{e}'



