# -*- coding: utf-8 -*-
# @Time    : 2025/11/15 11:43:41
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : auth.py
# @License : Apache-2.0
# @Desc    : 认证数据模型

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str
    image_code: str


class RegisterRequest(BaseModel):
    email: str
    username: str
    display_name: str
    password: str
    image_code: str
    verify_code: str


class ResetPasswordRequest(BaseModel):
    username: str
    email: str
    verify_code: str
    new_password: str
    image_code: str


class RefreshRequest(BaseModel):
    refresh_token: str


class VerifyCodeRequest(BaseModel):
    email: str


class PublicKeyRequest(BaseModel):
    public_key: str
