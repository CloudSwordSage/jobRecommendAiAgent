# -*- coding: utf-8 -*-
# @Time    : 2025/11/15 11:41:56
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : auth.py
# @License : Apache-2.0
# @Desc    : 认证 API

import random
import base64
import asyncio
from io import BytesIO
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException, status, Header, Request
from PIL import Image, ImageDraw, ImageFont

from schema.auth import (
    RegisterRequest,
    LoginRequest,
    ResetPasswordRequest,
    RefreshRequest,
    PublicKeyRequest,
)
from utils.security import (
    oauth2_scheme,
    get_current_user,
    create_access_token,
    decode_token,
    is_token_blacklisted,
    revoke_token,
    generate_rsa_key_pair,
    hash_password,
    verify_password,
    create_refresh_token,
    encrypt_to,
    decrypt_from,
)
from utils.database import get_redis, get_db
from jose import JWTError
from services.smtp import send_verify_code
from model.user import User
from services.telemetry import capture_exception

router = APIRouter(prefix="/auth")


@router.get("/image_code")
async def get_image_code(
    request: Request, rds=Depends(get_redis), x_session_id: str = Header(None)
):
    if not x_session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Session ID is required"
        )

    ip = request.state.client_ip

    # 生成6位随机数字验证码
    code = f"{random.randint(0, 999999):06d}"

    # 存入 Redis，覆盖原值，180秒过期
    await rds.set(f"image_code:{x_session_id}_{ip}", code, ex=180)

    def _make_image_base64() -> str:
        width = 165
        height = 60
        img = Image.new("RGB", (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default(size=35)
        x_pos = 0
        for ch in code:
            angle = random.randint(-45, 45)
            color = (
                random.randint(0, 150),
                random.randint(0, 150),
                random.randint(0, 150),
            )
            char_img = Image.new("RGBA", (40, 60), (255, 255, 255, 0))
            char_draw = ImageDraw.Draw(char_img)
            char_draw.text((10, 10), ch, font=font, fill=color)
            rotated = char_img.rotate(
                angle, resample=Image.Resampling.BICUBIC, expand=1
            )
            img.paste(rotated, (x_pos, 0), rotated)
            x_pos += 22
        for _ in range(6):
            x1 = random.randint(0, width)
            y1 = random.randint(0, height)
            x2 = random.randint(0, width)
            y2 = random.randint(0, height)
            draw.line((x1, y1, x2, y2), fill=(150, 150, 150), width=1)
        for _ in range(500):
            px = random.randint(0, width - 1)
            py = random.randint(0, height - 1)
            draw.point(
                (px, py),
                fill=(
                    random.randint(0, 255),
                    random.randint(0, 255),
                    random.randint(0, 255),
                ),
            )
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")

    img_base64 = await asyncio.to_thread(_make_image_base64)
    return {"image": f"data:image/png;base64,{img_base64}"}


@router.get("/verify_code")
async def get_verify_code(
    request: Request,
    email: str,
    x_session_id: str = Header(None),
    rds=Depends(get_redis),
):
    if not x_session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Session ID is required"
        )

    ip = request.state.client_ip

    # 生成6位随机数字验证码
    code = f"{random.randint(0, 999999):06d}"

    # 存入 Redis，覆盖原值，300秒过期
    await rds.set(f"verify_code:{x_session_id}_{ip}", code, ex=300)

    async def _send():
        try:
            await send_verify_code(verify_code=code, to_email=email)
        except Exception as e:
            capture_exception(e)

    task = asyncio.create_task(_send())
    return {"message": "Verify code sent"}


@router.post("/public_key")
async def upload_public_key(
    request: PublicKeyRequest,
    r: Request,
    x_session_id: str = Header(None),
    rds=Depends(get_redis),
):
    ip = r.state.client_ip
    await rds.set(
        f"client_public_key:{x_session_id}_{ip}", request.public_key, ex=604800
    )
    server_public_key, server_private_key = await asyncio.to_thread(
        generate_rsa_key_pair
    )
    await rds.set(
        f"server_private_key:{x_session_id}_{ip}", server_private_key, ex=604800
    )
    return {"message": "Public key uploaded", "public_key": server_public_key}


@router.post("/refresh")
async def refresh(
    request: RefreshRequest, rds=Depends(get_redis), authorization: str = Header(None)
):
    try:
        payload = decode_token(request.refresh_token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from e
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type"
        )
    jti = payload.get("jti")
    if not jti or await is_token_blacklisted(rds, jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked"
        )
    uid_str: str = payload.get("sub")
    username: str = payload.get("username")
    try:
        uid = int(uid_str)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid subject"
        ) from exc
    if authorization and authorization.lower().startswith("bearer "):
        old_token = authorization.split(" ", 1)[1].strip()
        with suppress(JWTError):
            old_payload = decode_token(old_token)
            if old_payload.get("type") == "access" and old_payload.get("sub") == str(
                uid
            ):
                await revoke_token(rds, old_token)

    access_token = create_access_token(uid, username)
    return {"access_token": access_token, "token_type": "Bearer"}


@router.post("/register")
async def register(
    request: RegisterRequest,
    r: Request,
    x_session_id: str = Header(None),
    db=Depends(get_db),
    rds=Depends(get_redis),
):
    ip = r.state.client_ip
    if not x_session_id:
        raise HTTPException(400, "Session ID is required")

    server_private_key = await rds.get(f"server_private_key:{x_session_id}_{ip}")
    if not server_private_key:
        raise HTTPException(400, "Private key not found")

    username = await asyncio.to_thread(
        decrypt_from, server_private_key, request.username
    )
    display_name = await asyncio.to_thread(
        decrypt_from, server_private_key, request.display_name
    )
    password = await asyncio.to_thread(
        decrypt_from, server_private_key, request.password
    )
    email = await asyncio.to_thread(decrypt_from, server_private_key, request.email)
    image_code_input = await asyncio.to_thread(
        decrypt_from, server_private_key, request.image_code
    )
    verify_code_input = await asyncio.to_thread(
        decrypt_from, server_private_key, request.verify_code
    )

    if await User.get_by_username(db, username):
        raise HTTPException(400, "Username already exists")

    image_key = f"image_code:{x_session_id}_{ip}"
    image_code_real = await rds.get(image_key)
    if not image_code_real or image_code_input != image_code_real:
        raise HTTPException(400, "Invalid or expired image code")

    mail_key = f"verify_code:{x_session_id}_{ip}"
    email_code_real = await rds.get(mail_key)
    if not email_code_real or verify_code_input != email_code_real:
        raise HTTPException(400, "Invalid or expired email code")

    if await User.get_by_username(db, username):
        raise HTTPException(400, "Username already exists")

    hashed_pw = await asyncio.to_thread(hash_password, password)

    new_user = User(
        username=username, display_name=display_name, email=email, password=hashed_pw
    )
    db.add(new_user)
    await db.commit()

    await rds.delete(image_key)
    await rds.delete(mail_key)
    return {"message": "Register success"}


@router.post("/login")
async def login(
    request: LoginRequest,
    r: Request,
    x_session_id: str = Header(None),
    db=Depends(get_db),
    rds=Depends(get_redis),
):
    ip = r.state.client_ip
    server_private_key = await rds.get(f"server_private_key:{x_session_id}_{ip}")
    if not server_private_key:
        raise HTTPException(400, "Private key not found")

    username = await asyncio.to_thread(
        decrypt_from, server_private_key, request.username
    )
    password = await asyncio.to_thread(
        decrypt_from, server_private_key, request.password
    )
    image_code_input = await asyncio.to_thread(
        decrypt_from, server_private_key, request.image_code
    )

    # 验证图形验证码
    image_code_real = await rds.get(f"image_code:{x_session_id}_{ip}")
    if not image_code_real or image_code_input != image_code_real:
        raise HTTPException(400, "Invalid image code")

    user = await User.get_by_username(db, username)
    if not user or not await asyncio.to_thread(
        verify_password, password, user.password
    ):
        raise HTTPException(401, "User or password incorrect")

    access_token = create_access_token(user.uid, user.username)
    refresh_token = create_refresh_token(user.uid, user.username)
    client_public_key = await rds.get(f"client_public_key:{x_session_id}_{ip}")
    uid_enc = await asyncio.to_thread(encrypt_to, client_public_key, str(user.uid))
    return {
        "uid": uid_enc,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
    }


@router.post("/logout")
async def logout(token: str = Depends(oauth2_scheme), rds=Depends(get_redis)):
    await revoke_token(rds, token)
    return {}


@router.get("/me")
async def get_me(
    r: Request,
    current_user=Depends(get_current_user),
    x_session_id: str = Header(None),
    rds=Depends(get_redis),
):
    ip = r.state.client_ip
    if not x_session_id:
        raise HTTPException(400, "Session ID is required")

    client_public_key = await rds.get(f"client_public_key:{x_session_id}_{ip}")
    if not client_public_key:
        raise HTTPException(400, "Client public key not found")
    enc_uid, enc_uname, enc_dname, enc_email = await asyncio.gather(
        asyncio.to_thread(encrypt_to, client_public_key, str(current_user.uid)),
        asyncio.to_thread(encrypt_to, client_public_key, current_user.username),
        asyncio.to_thread(encrypt_to, client_public_key, current_user.display_name),
        asyncio.to_thread(encrypt_to, client_public_key, current_user.email),
    )
    return {
        "uid": enc_uid,
        "username": enc_uname,
        "display_name": enc_dname,
        "email": enc_email,
    }


@router.post("/reset_password")
async def reset_password(
    request: ResetPasswordRequest,
    r: Request,
    x_session_id: str = Header(None),
    db=Depends(get_db),
    rds=Depends(get_redis),
):
    ip = r.state.client_ip
    if not x_session_id:
        raise HTTPException(400, "Session ID is required")

    server_private_key = await rds.get(f"server_private_key:{x_session_id}_{ip}")
    if not server_private_key:
        raise HTTPException(400, "Private key not found")

    username = await asyncio.to_thread(
        decrypt_from, server_private_key, request.username
    )
    new_password = await asyncio.to_thread(
        decrypt_from, server_private_key, request.new_password
    )
    verify_code_input = await asyncio.to_thread(
        decrypt_from, server_private_key, request.verify_code
    )
    image_code_input = await asyncio.to_thread(
        decrypt_from, server_private_key, request.image_code
    )

    image_key = f"image_code:{x_session_id}_{ip}"
    image_code_real = await rds.get(image_key)
    if not image_code_real or str(image_code_input) != str(image_code_real):
        raise HTTPException(400, "Invalid or expired image code")

    mail_key = f"verify_code:{x_session_id}_{ip}"
    email_code_real = await rds.get(mail_key)
    if not email_code_real or str(verify_code_input) != str(email_code_real):
        raise HTTPException(400, "Invalid or expired email code")

    user = await User.get_by_username(db, username)
    if not user:
        raise HTTPException(404, "User not found")

    user.password = await asyncio.to_thread(hash_password, new_password)
    db.add(user)
    await db.commit()

    await rds.delete(image_key)
    await rds.delete(mail_key)
    return {"message": "Password reset success"}
