import time
from time import sleep
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, DirCreatedEvent, FileCreatedEvent
import json
import io
import threading
import shutil
import subprocess
import re
import pysilk
import wave
import os

import config_service
from agents import AgentRegistry, claude_control, codex_control
from smtplib_service import send_email
import requests

LOGIN_INFO_URL = "http://127.0.0.1:3000/get_login_info"
MAX_SESSION_LIST_LINES = 30
DEFAULT_WATCH_DIR = os.path.expanduser(r"~\Documents\QQChatExporter\live-capture")

AGENT_REGISTRY = AgentRegistry()
AGENT_REGISTRY.register(codex_control, "codex")
AGENT_REGISTRY.register(claude_control, "claude")
_agent_status_lock = threading.RLock()
_agent_status_context = {'status': 'not_started', 'message': 'Agent 尚未启动'}


def get_current_session_context(uid: str):
    """Return the current configured workspace, session name and UUID."""
    user = config_service.dict_user_exist(uid)
    if not isinstance(user, dict):
        return None

    recent = user.get('recent_workspace_and_session', {})
    if not isinstance(recent, dict) or not recent:
        return None
    workspace, session = next(iter(recent.items()))
    workspaces = user.get('workspaces', {})
    if not isinstance(workspaces, dict):
        return None
    workspace_data = workspaces.get(workspace)
    if not isinstance(workspace_data, dict):
        return None
    sessions = workspace_data.get('sessions', {})
    if not isinstance(sessions, dict):
        return None
    return {
        'uid': uid,
        'workspace': workspace,
        'session': session,
        'session_id': config_service.session_id(sessions.get(session)),
        'agent': config_service.session_agent(sessions.get(session)),
    }


def get_current_session_id(uid: str):
    """Return the UUID of the QQ user's current configured session."""
    context = get_current_session_context(uid)
    return context.get('session_id') if context else None


def get_target_session_context(
    uid: str,
    workspace: str | None,
    session: str | None,
    agent: str | None = None,
):
    """Resolve the workspace/session and Agent that will handle this request.

    A switch command can target a different workspace or create a new session.
    Resolve that target before invoking Codex so the management page does not
    briefly display the previous session as active.
    """
    default_agent = config_service.get_default_agent()
    user = config_service.dict_user_exist(uid)
    if not isinstance(user, dict):
        return {
            'uid': uid,
            'workspace': workspace,
            'session': session,
            'session_id': None,
            'agent': agent or default_agent,
        }

    recent = user.get('recent_workspace_and_session', {})
    recent_workspace = next(iter(recent), None) if isinstance(recent, dict) else None
    target_workspace = workspace or recent_workspace
    if not target_workspace:
        return {
            'uid': uid,
            'workspace': None,
            'session': session,
            'session_id': None,
            'agent': agent or default_agent,
        }

    workspaces = user.get('workspaces', {})
    workspace_data = workspaces.get(target_workspace) if isinstance(workspaces, dict) else None
    sessions = workspace_data.get('sessions', {}) if isinstance(workspace_data, dict) else {}
    target_session = session
    if not target_session and target_workspace == recent_workspace and isinstance(recent, dict):
        target_session = recent.get(recent_workspace)

    value = sessions.get(target_session) if isinstance(sessions, dict) and target_session else None
    return {
        'uid': uid,
        'workspace': target_workspace,
        'session': target_session,
        'session_id': config_service.session_id(value),
        'agent': agent or (config_service.session_agent(value) if value is not None else default_agent),
    }


def publish_agent_status(status: str, **context) -> None:
    """Publish status without allowing status-file errors to affect Agent work."""
    with _agent_status_lock:
        _agent_status_context.clear()
        _agent_status_context.update({'status': status, **context})
        try:
            config_service.update_agent_status(status, **context)
        except OSError as e:
            print(f'写入 Agent 状态失败: {e}')


def heartbeat_agent_status() -> None:
    """Refresh the current status timestamp without changing its context."""
    with _agent_status_lock:
        context = dict(_agent_status_context)
        status = context.pop('status', 'idle')
        try:
            config_service.update_agent_status(status, **context)
        except OSError as e:
            print(f'写入 Agent 心跳失败: {e}')


def save_chat_record(
    uid: str,
    user_content: str,
    assistant_content: str,
    session_id: str | None = None,
) -> None:
    """Save a normal user/agent exchange under the selected session UUID."""
    try:
        session_id = session_id or get_current_session_id(uid)
        if not session_id:
            print(f'未找到 QQ {uid} 的会话 UUID，跳过聊天记录保存')
            return
        config_service.MemoryLine('user', user_content, session_id)
        config_service.MemoryLine('assistant', assistant_content, session_id)
    except (OSError, TypeError, ValueError, KeyError, AttributeError) as e:
        # 记录保存失败不应影响原有消息回复流程。
        print(f'保存 QQ {uid} 聊天记录失败: {e}')

def get_login_uid():
    """Return the QQ currently logged in to NapCat, or None if unavailable."""
    try:
        response = requests.get(LOGIN_INFO_URL, timeout=5)
        response.raise_for_status()
        return response.json()['data']['user_id']
    except requests.exceptions.ConnectionError:
        print("❌连接失败，服务没启动/端口没监听")
    except Exception as e:
        print(f'登录接口不可用（{LOGIN_INFO_URL}）：{e}')
    return None


def check_login_api() -> bool:
    user_id = get_login_uid()
    if user_id is None:
        return False
    print(f'登录接口可用，当前 QQ：{user_id}')
    return True


def silk_to_wav(silk_path: str, wav_path: str) -> bool:
    try:
        with open(silk_path, "rb") as source:
            # pysilk 需要文件对象，不能直接传入字节数组。
            output = io.BytesIO()
            pysilk.decode(source, output, 24000)
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(output.getvalue())
        return True
    except Exception as e:
        print(f"pysilk解码异常：{e}")
        return False


def amr_to_16k_wav(amr_path: str, wav_path: str) -> bool:
    """Silk 解码失败时，回退到 ffmpeg 的 AMR 转码。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg 不在 PATH 中，无法执行 AMR 回退转码")
        return False
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", amr_path,
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                wav_path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"AMR 回退转码启动失败：{exc}")
        return False
    if result.returncode != 0:
        print(f"AMR 回退转码失败：{result.stderr.strip()}")
        return False
    return os.path.isfile(wav_path) and os.path.getsize(wav_path) > 44


audio_model = None
audio_model_ready = threading.Event()


def load_audio_model() -> None:
    """后台加载大模型，避免文本命令被模型初始化阻塞。"""
    global audio_model
    config_service.update_audio_model_status('loading', '正在加载语音识别模型')
    try:
        from funasr import AutoModel
        audio_model = AutoModel(model="paraformer-zh", disable_update=True)
    except Exception as exc:
        config_service.update_audio_model_status('failed', f'模型加载失败：{exc}')
        print(f'模型加载失败：{exc}', flush=True)
        return
    audio_model_ready.set()
    config_service.update_audio_model_status('ready', '语音识别模型已就绪')
    print('模型加载成功', flush=True)


def wait_for_stable_size(path: str, attempts: int, require_content: bool) -> bool:
    """等待文件大小连续两次一致，表示导出程序已完成写入。"""
    previous_size = -1
    for _ in range(attempts):
        try:
            current_size = os.path.getsize(path)
        except OSError:
            current_size = -1
        if current_size == previous_size and (current_size > 0 or not require_content):
            return True
        previous_size = current_size
        sleep(0.2)
    return False


def wait_for_audio_file(audio_path: str) -> bool:
    """等待媒体文件写入完成，跳过空文件和尚未落盘的文件。"""
    return wait_for_stable_size(audio_path, 15, require_content=True)


class myFileSystemEventHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        # 按发送者保存待应用的切换参数，避免不同 QQ 用户互相覆盖。
        self.user_params = {}


    def on_created(self, event: DirCreatedEvent | FileCreatedEvent) -> None:
        # Media files, temporary WAVs and directories also land in the watch
        # tree; filter them before touching the NapCat HTTP API.
        if event.is_directory or not event.src_path.endswith('.jsonl'):
            return
        print(f'文件{event.src_path}被创建，获取接收方信息')
        receive_uid = get_login_uid()
        if receive_uid is None:
            return
        data_list=[]
        try:
            # 等待导出程序完成写入，避免读取到半条 JSONL。
            wait_for_stable_size(event.src_path, 10, require_content=False)
            with open(event.src_path,'r',encoding='utf-8') as f1:
                for line in f1:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data=json.loads(line)
                    except json.decoder.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    message = data.get('message')
                    if not isinstance(message, dict):
                        print('消息缺少 message 字段，已跳过')
                        continue
                    sender = message.get('sender')
                    content = message.get('content')
                    if not isinstance(sender, dict) or not isinstance(content, dict):
                        print('消息格式不完整，已跳过')
                        continue
                    send_uid = str(sender.get('uin') or '')
                    elements = content.get('elements')
                    if not send_uid or not isinstance(elements, list) or not elements:
                        print('消息缺少发送者或内容元素，已跳过')
                        continue
                    first_element = elements[0] if isinstance(elements[0], dict) else {}
                    message_type = first_element.get('type')
                    print(send_uid)
                    if message_type == 'text':
                        text = content.get('text')
                        if text:
                            data_list.append(str(text))
                            print(f'文件{event.src_path}读取成功')
                    elif message_type == 'audio':
                        media = data.get('media')
                        audio_path = (
                            media[0].get('localPath')
                            if isinstance(media, list) and media and isinstance(media[0], dict)
                            else None
                        )
                        if not isinstance(audio_path, str) or not wait_for_audio_file(audio_path):
                            send_email(receive_uid, send_uid, '语音文件尚未准备完成，请稍后重发。')
                            return
                        if not audio_model_ready.wait(timeout=120):
                            send_email(receive_uid, send_uid, '语音识别模型仍在加载，请稍后重发。')
                            return
                        wav_path = os.path.splitext(audio_path)[0] + '.wav'
                        try:
                            decoded = silk_to_wav(audio_path, wav_path)
                            if not decoded:
                                print('Silk 解码失败，尝试 AMR 回退转码')
                                decoded = amr_to_16k_wav(audio_path, wav_path)
                            if not decoded:
                                send_email(receive_uid, send_uid, '语音解码失败，暂时无法识别该语音。')
                                return
                            text_list = audio_model.generate(input=wav_path)
                            text = text_list[0].get('text') if text_list and isinstance(text_list[0], dict) else ''
                            data_list.append(text or '未识别到内容')
                            print(f'识别内容为:{text}')
                        except Exception as e:
                            print(f'文件{event.src_path}语音识别失败:{e}')
                            send_email(receive_uid, send_uid, '语音识别失败，请稍后重试。')
                            return
                        finally:
                            try:
                                if os.path.exists(wav_path):
                                    os.remove(wav_path)
                            except OSError as e:
                                print(f'清理临时语音文件失败: {e}')
                combined_text = ''.join(data_list)
                command = combined_text.strip().lower()
                if command == '/help':
                    available_agents = '、'.join(sorted(AGENT_REGISTRY.agent_dict))
                    send_email(
                        receive_uid,
                        send_uid,
                        'QCCA命令帮助：\n'
                        '/help - 查看帮助\n'
                        '/status - 查看当前工作区和会话\n'
                        '/sessions - 列出已保存的工作区和会话\n'
                        '/cancel - 仅取消待生效的切换参数，不会结束当前会话\n'
                        '/agent - 查看当前 Agent 和可用 Agent\n'
                        '/agent=codex 或 /agent=claude - 下一条消息使用指定 Agent\n'
                        '/workspace="路径" session=会话 sandbox=权限 agent=Agent - 切换工作区、会话和 Agent\n'
                        'sandbox 可选：read-only、workspace-write、danger-full-access\n'
                        f'当前可用 Agent：{available_agents}\n'
                        '发送切换命令后，再发送一条普通消息即可生效。',
                    )
                    return
                if command == '/agent':
                    current = get_current_session_context(send_uid) or {}
                    pending = self.user_params.get(send_uid, {})
                    current_agent = pending.get('agent') or current.get('agent') or 'codex'
                    available_agents = '、'.join(sorted(AGENT_REGISTRY.agent_dict))
                    suffix = '（待下一条消息生效）' if pending.get('agent') else ''
                    send_email(
                        receive_uid,
                        send_uid,
                        f'当前 Agent：{current_agent}{suffix}\n'
                        f'可用 Agent：{available_agents}\n'
                        '切换方式：/agent=codex 或 /agent=claude',
                    )
                    return
                if command == '/cancel':
                    self.user_params.pop(send_uid, None)
                    send_email(receive_uid, send_uid, '已取消待生效的切换参数。')
                    return
                if command in {'/status', '/sessions'}:
                    user = config_service.dict_user_exist(send_uid)
                    if not user:
                        send_email(receive_uid, send_uid, '当前 QQ 还没有保存的工作区或会话。')
                        return
                    if command == '/status':
                        workspace, _ = config_service.get_user_recent_session(user)
                        recent = user.get('recent_workspace_and_session', {})
                        session = recent.get(workspace) if workspace else None
                        workspace_data = user.get('workspaces', {}).get(workspace, {})
                        sandbox = workspace_data.get('sandbox')
                        session_data = workspace_data.get('sessions', {}).get(session, {})
                        agent = config_service.session_agent(session_data)
                        send_email(receive_uid, send_uid,
                                   f'当前工作区：{workspace or "未设置"}\n'
                                   f'当前会话：{session or "未设置"}\n'
                                   f'当前 Agent：{agent}\n'
                                   f'沙箱权限：{sandbox or "read-only"}')
                    else:
                        lines = ['已保存的工作区和会话：']
                        for workspace, data in user.get('workspaces', {}).items():
                            session_items = []
                            for name, value in data.get('sessions', {}).items():
                                sid = config_service.session_id(value)
                                agent = config_service.session_agent(value)
                                label = f'{name}（{sid}）' if sid else str(name)
                                session_items.append(f'{label} [{agent}]')
                            sessions = ', '.join(session_items)
                            lines.append(f'- {workspace}: {sessions or "无会话"}')
                            if len(lines) >= MAX_SESSION_LIST_LINES:
                                lines.append('... 内容过长，已截断。')
                                break
                        send_email(receive_uid, send_uid, '\n'.join(lines))
                    return
                if config_service.is_sandbox_command(combined_text):
                    parse_sandbox_params_dict = config_service.parse_sandbox_params(combined_text)
                    if any(value is not None for value in parse_sandbox_params_dict.values()):
                        # Merge partial switch commands so /agent and
                        # /workspace commands can be sent separately.
                        pending = self.user_params.get(send_uid, {})
                        pending = {
                            key: pending.get(key)
                            for key in ("workspace", "sandbox", "session", "agent")
                        }
                        for key, value in parse_sandbox_params_dict.items():
                            if value is not None:
                                pending[key] = value
                        self.user_params[send_uid] = pending
                        send_email(receive_uid, send_uid,
                                   f'读到有效配置，workspace:{pending["workspace"]},'
                                   f'sandbox:{pending["sandbox"]},'
                                   f'session:{pending["session"]},'
                                   f'agent:{pending["agent"]}')
                        return
                    else:
                        if re.search(r'\bagent=', combined_text, re.IGNORECASE):
                            send_email(receive_uid, send_uid, 'Agent 无效，可选：codex、claude。')
                            return
                        send_email(receive_uid, send_uid, '未读到有效配置')
                        return
                elif combined_text.strip().startswith('/'):
                    send_email(receive_uid, send_uid, '未知指令。发送 /help 查看可用命令。')
                    return
                else:
                    print('准备调用agent')
                    # 调用agent获取agent输出
                    if not data_list or not send_uid:
                        print('没有可处理的消息')
                        return
                    params = self.user_params.pop(send_uid, {})
                    current = get_current_session_context(send_uid) or {}
                    target = get_target_session_context(
                        send_uid,
                        params.get('workspace'),
                        params.get('session'),
                        params.get('agent'),
                    )
                    agent_name = target.get('agent') or 'codex'
                    agent_control = AGENT_REGISTRY.get_agent(agent_name)
                    if agent_control is None:
                        print(f'未知 Agent 类型 {agent_name}，回退到 codex')
                        agent_name = 'codex'
                        agent_control = AGENT_REGISTRY.get_agent(agent_name)
                    if agent_control is None:
                        send_email(receive_uid, send_uid, '没有可用的编码 Agent。')
                        return
                    publish_agent_status(
                        'running',
                        uid=send_uid,
                        workspace=target.get('workspace') or current.get('workspace'),
                        session=target.get('session') or '待创建',
                        session_id=target.get('session_id'),
                        agent=agent_name,
                        message=f'正在调用 {agent_name} Agent',
                    )
                    try:
                        agent_text = agent_control(
                            send_uid,
                            combined_text,
                            params.get('workspace'),
                            params.get('session'),
                            params.get('sandbox'),
                            agent=agent_name,
                        )
                    except Exception as exc:
                        failed = get_current_session_context(send_uid) or current
                        publish_agent_status(
                            'failed',
                            uid=send_uid,
                            workspace=failed.get('workspace') or target.get('workspace'),
                            session=failed.get('session') or target.get('session'),
                            session_id=failed.get('session_id') or target.get('session_id'),
                            agent=agent_name,
                            message=f'Agent 调用失败：{exc}',
                        )
                        print(f'Agent 调用失败：{exc}')
                        send_email(receive_uid, send_uid, f'Agent 调用失败：{exc}')
                        return
                    finished = get_current_session_context(send_uid) or current
                    finished_agent = finished.get('agent') or agent_name
                    publish_agent_status(
                        'idle',
                        uid=send_uid,
                        workspace=finished.get('workspace'),
                        session=finished.get('session'),
                        session_id=finished.get('session_id'),
                        agent=finished_agent,
                        message='Agent 空闲',
                    )
                    print(agent_text)
                    target_matches_finished = (
                        target.get('workspace') == finished.get('workspace')
                        and target.get('session') == finished.get('session')
                    )
                    record_session_id = target.get('session_id')
                    if target_matches_finished:
                        record_session_id = record_session_id or finished.get('session_id')
                    if record_session_id:
                        save_chat_record(
                            send_uid,
                            combined_text,
                            agent_text,
                            record_session_id,
                        )
                    else:
                        print('目标会话未成功落盘，跳过聊天记录保存')
                    send_email(receive_uid, send_uid, agent_text)
        except Exception as e:
            print(f'文件{event.src_path}处理失败:{e}')


if __name__ == '__main__':
    print('程序开始', flush=True)
    check_login_api()
    publish_agent_status('idle', message='Agent 已启动')
    threading.Thread(target=load_audio_model, name='qcca-audio-model', daemon=True).start()
    # 创建记录目录；config_dir_file() 同时创建工作目录和空配置文件。
    os.makedirs(os.path.join(config_service.qcca_home(), 'record'), exist_ok=True)
    config_service.config_dir_file()
    myhandler=myFileSystemEventHandler()
    print('开始监听文件夹', flush=True)
    observer = Observer()
    watch_dir = os.path.abspath(os.path.expandvars(
        os.getenv('QCCA_WATCH_DIR', DEFAULT_WATCH_DIR)
    ))
    os.makedirs(watch_dir, exist_ok=True)
    print(f'监听目录：{watch_dir}', flush=True)
    observer.schedule(myhandler, watch_dir, recursive=True)
    print("开始监听文件夹，按 Ctrl+C 退出", flush=True)
    observer.start()  # 后台线程开始监听

    try:
        audio_heartbeat_at = 0.0
        agent_heartbeat_at = 0.0
        while True:
            time.sleep(1)
            now = time.monotonic()
            if audio_model_ready.is_set() and now - audio_heartbeat_at >= 5:
                config_service.update_audio_model_status('ready', '语音识别模型已就绪')
                audio_heartbeat_at = now
            if now - agent_heartbeat_at >= 5:
                heartbeat_agent_status()
                agent_heartbeat_at = now
    except KeyboardInterrupt:
        # 按下ctrl+c触发
        print("\n准备停止监听")
        publish_agent_status('stopped', message='Agent 已停止')
        observer.stop()

        observer.join()  # 等待observer线程完全结束
        print("程序退出")
