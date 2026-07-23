"""SMTP 发信。支持 SSL(465) 与 STARTTLS(587/25)，自动按端口选择。

163 邮箱示例（推荐 SSL 465）：
    SMTP_HOST=smtp.163.com
    SMTP_PORT=465
    SMTP_USERNAME=wk1924321@163.com
    SMTP_PASSWORD=<邮箱授权码，不是登录密码!>
    SMTP_FROM=wk1924321@163.com
    SMTP_TO=wk1924321@163.com
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

logger = logging.getLogger(__name__)


def _env(*names):
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return None


def send_email(subject: str, html_body: str, text_body: str) -> bool:
    host = _env("SMTP_HOST")
    port = _env("SMTP_PORT")
    username = _env("SMTP_USERNAME", "SMTP_USER")
    password = _env("SMTP_PASSWORD", "SMTP_PASS")
    from_email = _env("SMTP_FROM") or username
    to_email = _env("SMTP_TO") or username

    if not all([host, port, username, password, from_email, to_email]):
        logger.warning("SMTP 未完整配置（需要 SMTP_HOST/PORT/USERNAME/PASSWORD/FROM/TO），跳过发信。")
        return False

    port = int(port)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("每日简报", "utf-8")), from_email))
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # 支持多个收件人（逗号分隔）
    recipients = [x.strip() for x in to_email.split(",") if x.strip()]

    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.ehlo()
            server.starttls()
            server.ehlo()
        with server:
            server.login(username, password)
            server.sendmail(from_email, recipients, msg.as_string())
        logger.info("邮件已发送至 %s", to_email)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("邮件发送失败: %s", exc)
        return False
