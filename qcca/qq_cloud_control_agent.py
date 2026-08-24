import time
from time import sleep
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, DirCreatedEvent, FileCreatedEvent
import json
import io
import threading
import pysilk
import wave
import os

import config_service
from codex_service import codex_run
from smtplib_service import send_email
import requests

LOGIN_INFO_URL = "http://127.0.0.1:3000/get_login_info"
MAX_SESSION_LIST_LINES = 30
DEFAULT_WATCH_DIR = os.path.expanduser(r"~\Documents\QQChatExporter\live-capture")

def check_login_api() -> bool:
    try:
        response = requests.get(LOGIN_INFO_URL, timeout=5)
        response.raise_for_status()
        user_id = response.json().get('data', {}).get('user_id')
        print(f'登录接口可用，当前 QQ：{user_id}')
        return True
    except requests.RequestException as e:
        print(f'登录接口不可用（{LOGIN_INFO_URL}）：{e}')
        return False


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


def wait_for_audio_file(audio_path: str) -> bool:
    """等待媒体文件写入完成，跳过空文件和尚未落盘的文件。"""
    previous_size = -1
    for _ in range(15):
        try:
            current_size = os.path.getsize(audio_path)
        except OSError:
            current_size = -1
        if current_size > 0 and current_size == previous_size:
            return True
        previous_size = current_size
        sleep(0.2)
    return False
class myFileSystemEventHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        # 按发送者保存待应用的切换参数，避免不同 QQ 用户互相覆盖。
        self.user_params = {}


    def on_created(self, event: DirCreatedEvent | FileCreatedEvent) -> None:
        print('获取接收方信息')
        url = LOGIN_INFO_URL

        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()  # 如果http错误(404/500)抛异常
            print(resp.status_code)
            resp_data=resp.json()
            print(resp_data)
            receive_uid=resp_data['data']['user_id']
            # 返回json直接解析
        except requests.exceptions.ConnectionError:
            print("❌连接失败，服务没启动/端口没监听")
            return
        except Exception as e:
            print("异常：", e)
            return
        if not event.is_directory:
            print(f'文件{event.src_path}被创建')
            if event.src_path.endswith('.jsonl'):
                print('文件格式为jsonl')
                data_list=[]
                # 等待导出程序完成写入，避免读取到半条 JSONL。
                previous_size = -1
                for _ in range(10):
                    current_size = os.path.getsize(event.src_path)
                    if current_size == previous_size:
                        break
                    previous_size = current_size
                    sleep(0.2)
                try:
                    with open(event.src_path,'r',encoding='utf-8') as f1:
                        for line in f1:
                            line = line.strip()
                            print(line)
                            if not line:
                                continue
                            try:
                                data=json.loads(line)
                            except json.decoder.JSONDecodeError:
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
                                    if not silk_to_wav(audio_path, wav_path):
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
                        parse_sandbox_params_dict=config_service.parse_sandbox_params(''.join(data_list))
                        combined_text = ''.join(data_list)
                        command = combined_text.strip().lower()
                        if command == '/help':
                            send_email(
                                receive_uid,
                                send_uid,
                                'QCCA命令帮助：\n'
                                '/help - 查看帮助\n'
                                '/status - 查看当前工作区和会话\n'
                                '/sessions - 列出已保存的工作区和会话\n'
                                '/cancel - 仅取消待生效的切换参数，不会结束当前会话\n'
                                '/workspace="路径" session=会话 sandbox=权限 - 切换工作区和会话\n'
                                'sandbox 可选：read-only、workspace-write、danger-full-access\n'
                                '发送切换命令后，再发送一条普通消息即可生效。',
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
                                sandbox = user.get('workspaces', {}).get(workspace, {}).get('sandbox')
                                send_email(receive_uid, send_uid,
                                           f'当前工作区：{workspace or "未设置"}\n'
                                           f'当前会话：{session or "未设置"}\n'
                                           f'沙箱权限：{sandbox or "read-only"}')
                            else:
                                lines = ['已保存的工作区和会话：']
                                for workspace, data in user.get('workspaces', {}).items():
                                    sessions = ', '.join(str(item) for item in data.get('sessions', {}).keys())
                                    lines.append(f'- {workspace}: {sessions or "无会话"}')
                                    if len(lines) >= MAX_SESSION_LIST_LINES:
                                        lines.append('... 内容过长，已截断。')
                                        break
                                send_email(receive_uid, send_uid, '\n'.join(lines))
                            return
                        if config_service.is_sandbox_command(combined_text):
                            if parse_sandbox_params_dict != {"workspace": None, "sandbox": None, "session": None}:
                                self.user_params[send_uid] = parse_sandbox_params_dict
                                send_email(receive_uid, send_uid,
                                           f'读到有效配置,workspace:{parse_sandbox_params_dict["workspace"]},sandbox:{parse_sandbox_params_dict["sandbox"]},session:{parse_sandbox_params_dict["session"]}')
                                return
                            else:
                                send_email(receive_uid, send_uid, '未读到有效配置')
                                return
                        else:
                            print('准备调用agent')
                            # 调用agent获取agent输出
                            if not data_list or not send_uid:
                                print('没有可处理的消息')
                                return
                            params = self.user_params.pop(send_uid, {})
                            agent_text = codex_run(
                                send_uid,
                                combined_text,
                                params.get('workspace'),
                                params.get('session'),
                                params.get('sandbox'),
                            )
                            # print(''.join(data_list))
                            print(agent_text)
                            send_email(receive_uid, send_uid, agent_text)
                except Exception as e:
                    print(f'文件{event.src_path}处理失败:{e}')
            # 被优化了
            # if event.src_path.endswith('.amr'):
            #     print('文件格式为amr')
            #     # 处理amr文件
            #     sleep(1)
            #     if(silk_to_wav(event.src_path,event.src_path.replace('.amr','.wav'))):
            #         print('amr转wav成功')
            #         # 处理wav文件
            #         text_dict=  model.generate(input=event.src_path.replace('.amr','.wav'))
            #         try:
            #             text=text_dict[0]['text'] if text_dict[0]['text']!=''and text_dict[0]['text']!=None else '未识别到内容'
            #             print('识别的内容为:'+text)
            #         except Exception as e:
            #             print(f'生成失败{e}')
            #     else:
            #         print('amr转wav失败')
if __name__ == '__main__':
    print('程序开始', flush=True)
    check_login_api()
    threading.Thread(target=load_audio_model, name='qcca-audio-model', daemon=True).start()
    #创建系统目录
    work_path=os.path.expanduser(r'~\.qq-chat-exporter\qcca')
    os.makedirs(work_path,exist_ok=True)
    #创建工作目录
    os.makedirs(work_path+r'\workspace',exist_ok=True)
    with open(work_path+r'\workspace\config.json','a',encoding='utf-8') as f:
        pass
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
        heartbeat_at = 0.0
        while True:
            time.sleep(1)
            if audio_model_ready.is_set() and time.monotonic() - heartbeat_at >= 5:
                config_service.update_audio_model_status('ready', '语音识别模型已就绪')
                heartbeat_at = time.monotonic()
    except KeyboardInterrupt:
        # 按下ctrl+c触发
        print("\n准备停止监听")
        observer.stop()

        observer.join()  # 等待observer线程完全结束
        print("程序退出")


