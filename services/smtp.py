# -*- coding: utf-8 -*-
# @Time    : 2025/11/16 16:09:06
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : smtp.py
# @License : Apache-2.0
# @Desc    : SMTP服务

import asyncio
import aiosmtplib
from email.message import EmailMessage

from config import Config

smtp = aiosmtplib.SMTP(hostname=Config.email_host, port=Config.email_port, use_tls=True)
smtp_lock = asyncio.Lock()


async def connect_smtp():
    """连接SMTP服务器"""
    async with smtp_lock:
        if not smtp.is_connected:
            await smtp.connect()
            await smtp.login(Config.email_user, Config.email_password)


async def disconnect_smtp():
    """断开SMTP连接"""
    async with smtp_lock:
        if smtp.is_connected:
            await smtp.quit()


async def send_email(
    subject: str, body: str, to_email: str, from_email: str = Config.email_user
):
    """发送邮件"""
    await connect_smtp()
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    async with smtp_lock:
        await smtp.send_message(msg)


async def send_verify_code(
    verify_code: str, to_email: str, from_email: str = Config.email_user
):
    """发送验证码邮件"""
    subject = "您的验证码"
    body = f"您的验证码为: {verify_code}\n请在5分钟内输入。如未请求，请忽略此邮件。"
    await send_email(subject, body, to_email, from_email)
