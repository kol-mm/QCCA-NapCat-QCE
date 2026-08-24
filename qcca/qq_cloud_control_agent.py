import time
from time import sleep
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, DirCreatedEvent, FileCreatedEvent
import json
import subprocess
from funasr import AutoModel
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


#构建qq用户字典对象
def silk_to_wav(silk_path: str, wav_path: str) -> bool:
    try:
        with open(silk_path, "rb") as f:
            raw = f.read()
        # 解码silk v3，输出pcm字节，采样率24000
        pcm_bytes = pysilk.decode(raw, sample_rate=24000)

        # 用python标准库wave写wav，不用pysilk自带不存在的write_wav
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm_bytes)
        return True
    except Exception as e:
        print(f"pysilk解码异常：{e}")
        return False
def amr_to_16k_wav(amr_file: str, wav_out: str) -> bool:
    """amr转asr标准wav：16000采样率，单声道 pcm_s16le"""
    cmd = [
        "ffmpeg",
        "-i", amr_file,
        "-y",          #自动覆盖输出
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",    #单声道
        wav_out
    ]
    ret = subprocess.run(cmd, capture_output=True, text=True)
    if ret.returncode != 0:
        print(f"转码失败：{ret.stderr}")
        return False
    return True
config_service.update_audio_model_status('loading', '正在加载语音识别模型')
try:
    model = AutoModel(model="paraformer-zh", disable_update=True)
except Exception as exc:
    config_service.update_audio_model_status('failed', f'模型加载失败：{exc}')
    raise
config_service.update_audio_model_status('ready', '语音识别模型已就绪')
print('模型加载成功', flush=True)
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
                            #获取qq账号
                            send_uid=data['message']['sender']['uin']
                            print(send_uid)
                            #获取用户输入内容
                            if(data['message']['content']['elements'][0]['type'] == 'text'):
                                text = data['message']['content'].get('text')
                                if text:

                                    data_list.append(text)
                                    print(f'文件{event.src_path}读取成功')
                            if(data['message']['content']['elements'][0]['type'] == 'audio'):
                                print('文件格式为amr')
                                sleep(1)
                                audio_path = data['media'][0].get('localPath')
                                if not audio_path:
                                    print('音频路径为空')
                                    continue
                                wav_path = audio_path.replace('.amr', '.wav')
                                if(silk_to_wav(audio_path, wav_path)):
                                    print('amr转wav成功')
                                    try:
                                        text_list=model.generate(wav_path)
                                        text = text_list[0]['text'] if text_list[0]['text'] != '' and text_list[0]['text'] != None else '未识别到内容'
                                        data_list.append(text)
                                        print(f'识别内容为:{text}')
                                    except Exception as e:
                                        print(f'文件{event.src_path}读取失败:{e}')
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
    #创建系统目录
    work_path=os.path.expanduser(r'~\.qq-chat-exporter\qcca')
    os.makedirs(work_path,exist_ok=True)
    #创建工作目录
    os.makedirs(work_path+r'\workspace',exist_ok=True)
    with open(work_path+r'\workspace\config.json','a',encoding='utf-8') as f:
        pass
    myhandler=myFileSystemEventHandler()
    observer = Observer()
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

        # 主线程循环，保持程序不退出
    try:
        heartbeat_at = 0.0
        while True:
                time.sleep(1)
                if time.monotonic() - heartbeat_at >= 5:
                    config_service.update_audio_model_status('ready', '语音识别模型已就绪')
                    heartbeat_at = time.monotonic()
    except KeyboardInterrupt:
        # 按下ctrl+c触发
        print("\n准备停止监听")
        observer.stop()

        observer.join()  # 等待observer线程完全结束
        print("程序退出")


