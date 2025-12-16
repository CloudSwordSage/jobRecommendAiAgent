# -*- coding: utf-8 -*-
# @Time    : 2025/11/15 11:16:27
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : security.py
# @License : Apache-2.0
# @Desc    : 安全相关工具

import os
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization
import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from jose import jwt, JWTError
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer

from config.config import Config
from model.user import User
from utils.database import get_db, get_redis
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# 公钥加密
def encrypt_to(public_key: str | bytes, message: str) -> str:
    """
    对消息进行加密
    Params:
        public_key (str | bytes): 公钥 PEM 格式字符串或 bytes
        message (str): 待加密消息
    Returns:
        str: 加密后的消息（Base64 编码）
    """
    if isinstance(public_key, str):
        public_key_bytes = public_key.encode()
    else:
        public_key_bytes = public_key

    if b"-----BEGIN" not in public_key_bytes:
        try:
            public_key_bytes = base64.b64decode(public_key_bytes)
        except Exception as e:
            raise ValueError("Invalid public key encoding") from e

    key_obj = serialization.load_pem_public_key(public_key_bytes)
    encrypted = key_obj.encrypt(
        message.encode(),
        padding.PKCS1v15(),
    )
    return base64.b64encode(encrypted).decode()


# 私钥解密
def decrypt_from(private_key: str | bytes, encrypted_message: str) -> str:
    """
    对消息进行解密
    Params:
        private_key (str | bytes): 私钥 PEM 格式字符串或 bytes
        encrypted_message (str): 待解密消息（Base64 编码）
    Returns:
        str: 解密后的消息
    """
    if isinstance(private_key, str):
        private_key_bytes = private_key.encode()
    else:
        private_key_bytes = private_key

    key_obj = serialization.load_pem_private_key(private_key_bytes, password=None)
    decrypted = key_obj.decrypt(
        base64.b64decode(encrypted_message),
        padding.PKCS1v15(),
    )
    return decrypted.decode()


# 生成RSA密钥对
def generate_rsa_key_pair() -> tuple:
    """
    生成RSA密钥对
    Returns:
        tuple: 包含公钥和私钥的元组
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return (
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode(),
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode(),
    )


JWT_ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def _build_payload(
    uid: int, username: str, token_type: str, expires_delta: timedelta
) -> dict:
    now = datetime.now(timezone.utc)
    exp = now + expires_delta
    return {
        "sub": str(uid),
        "username": username,
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }


def create_access_token(uid: int, username: str) -> str:
    if not Config.jwt_secret:
        raise RuntimeError("jwt_secret not configured")
    payload = _build_payload(
        uid, username, "access", timedelta(minutes=Config.access_token_expires_minutes)
    )
    return jwt.encode(payload, Config.jwt_secret, algorithm=JWT_ALGORITHM)


def create_refresh_token(uid: int, username: str) -> str:
    if not Config.jwt_secret:
        raise RuntimeError("jwt_secret not configured")
    payload = _build_payload(
        uid, username, "refresh", timedelta(days=Config.refresh_token_expires_days)
    )
    return jwt.encode(payload, Config.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    if not Config.jwt_secret:
        raise RuntimeError("jwt_secret not configured")
    return jwt.decode(token, Config.jwt_secret, algorithms=[JWT_ALGORITHM])


async def is_token_blacklisted(rds: redis.Redis, jti: str) -> bool:
    key = f"jwt:blacklist:{jti}"
    val = await rds.get(key)
    return val is not None


async def blacklist_token(rds: redis.Redis, jti: str, exp_ts: int) -> None:
    ttl = max(exp_ts - int(datetime.now(timezone.utc).timestamp()), 0)
    key = f"jwt:blacklist:{jti}"
    await rds.set(key, "1", ex=ttl)


async def revoke_token(rds: redis.Redis, token: str) -> None:
    try:
        payload = decode_token(token)
    except JWTError:
        return
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        await blacklist_token(rds, jti, int(exp))


async def validate_access_token(token: str, rds: redis.Redis) -> dict:
    try:
        payload = decode_token(token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from e
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type"
        )
    jti = payload.get("jti")
    if not jti or await is_token_blacklisted(rds, jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked"
        )
    return payload


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
    rds: redis.Redis = Depends(get_redis),
) -> User:
    payload = await validate_access_token(token, rds)
    from model.user import User

    uid_str = payload.get("sub")
    try:
        uid = int(uid_str)
    except (TypeError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid subject"
        ) from e
    user = await User.get_by_uid(db, uid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return user
