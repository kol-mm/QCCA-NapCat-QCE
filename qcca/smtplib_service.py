import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr  # 导入这个标准工具

import config_service

def send_email(
    sender: str,
    receiver: str,
    message: str,
):
    smtp_config = config_service.get_smtp_config()
    sender = smtp_config["sender_qq"] or sender
    mail_host = "smtp.qq.com"
    mail_user = f"{sender}@qq.com"
    mail_pass = smtp_config["auth_code"]
    if not mail_pass:
        raise RuntimeError("未设置环境变量 QCCA_SMTP_AUTH_CODE")

    sender_addr =f"{sender}@qq.com"
    receivers = [f"{receiver}@qq.com"]

    message = MIMEText(message, 'plain', 'utf-8')

    # 标准库生成合规From头，处理中文昵称
    message['From'] = formataddr(("agent通知", sender_addr))
    message['To'] = ",".join(receivers)
    message['Subject'] = Header("agent回复消息", "utf-8").encode()

    try:
        with smtplib.SMTP_SSL(mail_host, 465) as smtpObj:
            smtpObj.login(mail_user, mail_pass)
            smtpObj.sendmail(sender_addr, receivers, message.as_string())
        print("邮件发送成功")
    except smtplib.SMTPException as e:
        print(f"Error: 无法发送邮件,详情:{e}")
