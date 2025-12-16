# -*- coding: utf-8 -*-
# @Time    : 2025/11/16 13:53:15
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : sessions.py
# @License : Apache-2.0
# @Desc    : 聊天会话 API

import json
import copy
import uuid
import asyncio
from bson import ObjectId
from sqlalchemy import func
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from model.session import Session
from model.user import User
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from utils.security import get_current_user
from utils.database import get_db, get_redis, get_mongo, get_neo4j, neo4j_driver
from config import MAIN_SYSTEM_PROMPT
from services.llm import (
    load_portrait_data,
    chat_doubao,
    generate_character_portrait,
    compress_message,
    job_search_topn,
    rename_session_name,
)
from tokenizer import get_messages_token_count
from services.data import (
    increment_save_chat_history,
    save_compress_data,
    load_all_messages,
    load_messages,
)
from typing import AsyncGenerator

router = APIRouter(prefix="/session")


@router.get("/create")
async def create_session(
    r: Request,
    x_session_id: str = Header(None),
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
    rds=Depends(get_redis),
):
    session_id = str(uuid.uuid4())
    uid = current_user.uid
    redis_key = f"{uid}:session"
    await rds.set(redis_key, session_id, ex=7 * 24 * 60 * 60)
    messages = [{"role": "system", "content": MAIN_SYSTEM_PROMPT}]
    messages_key = f"session:{session_id}:messages"
    await rds.set(
        messages_key, json.dumps(messages, ensure_ascii=False), ex=24 * 60 * 60
    )
    session = Session(sid=session_id, uid=uid, session_name="新会话")
    db.add(session)
    await db.flush()
    await db.refresh(session)
    await db.commit()
    return {
        "session_id": session_id,
        "session_name": session.session_name,
        "create_time": session.create_time,
    }


@router.post("/chat")
async def chat_session(
    chat_request: str,
    current_user=Depends(get_current_user),
    r: Request = None,
    x_session_id: str = Header(None),
    db: AsyncSession = Depends(get_db),
    rds=Depends(get_redis),
    mongo=Depends(get_mongo),
    neo4j=Depends(get_neo4j),
):
    uid = current_user.uid
    redis_key = f"{uid}:session"
    session_id = await rds.get(redis_key)
    if not session_id:
        return {"error": "会话不存在"}

    messages_key = f"session:{session_id}:messages"
    messages_json = await rds.get(messages_key)
    if not messages_json:
        return {"error": "会话不存在"}
    messages: list[dict[str, str]] = json.loads(messages_json)
    character_portrait = await load_portrait_data(neo4j, session_id)
    messages.append(
        {
            "role": "user",
            "content": f"人物画像: {character_portrait}\n用户问题: {chat_request}",
        }
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        nonlocal messages
        await increment_save_chat_history(mongo, session_id, "user", chat_request)
        print(f"user: {chat_request}")

        async def stream_model(msgs):
            async for c in chat_doubao(msgs, stream=True):
                yield c

        tool_buffer = ""
        head = ""
        assistant_buffer = ""
        in_tool_call = False
        stream_mode_locked = False

        model_stream = stream_model(messages)

        while True:
            try:
                chunk = await model_stream.__anext__()
                # print(f"chunk: {chunk}")
            except StopAsyncIteration:
                if assistant_buffer.strip():
                    # 持久化助手回复
                    await increment_save_chat_history(
                        mongo, session_id, "assistant", assistant_buffer
                    )
                    print(f"assistant_buffer: {assistant_buffer}")
                    messages.append({"role": "assistant", "content": assistant_buffer})
                    tokens = await get_messages_token_count(messages)
                    # 200k tokens 压缩, chat_doubao 支持 256k 上下文
                    if tokens > 200000:
                        compress_data = await compress_message(messages)
                        await save_compress_data(mongo, session_id, compress_data)
                        messages = [
                            {"role": "system", "content": MAIN_SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": f"上下文超限, 请使用压缩数据重启: {compress_data}",
                            },
                        ]
                    # 缓存 + 重置过期时间
                    await rds.set(
                        messages_key,
                        json.dumps(messages, ensure_ascii=False),
                        ex=24 * 60 * 60,
                    )
                    # 后台生成人物画像
                    messages_snapshot = copy.deepcopy(messages[:-20])

                    async def _bg_portrait_task(snapshot, sid):
                        async with neo4j_driver.session() as neo4j_session:
                            await generate_character_portrait(
                                user_messages=snapshot,
                                session_id=sid,
                                neo4j_session=neo4j_session,
                            )

                    asyncio.create_task(
                        _bg_portrait_task(messages_snapshot, session_id)
                    )
                    # 后台重命名会话
                    asyncio.create_task(
                        rename_session_name(
                            copy.deepcopy(messages), session_id=session_id, db=db
                        )
                    )
                break

            if not in_tool_call:
                if len(head) < 12:
                    head += chunk
                    continue

                if not stream_mode_locked:
                    if head.startswith("[TOOL_CALL]"):
                        in_tool_call = True
                        continue
                    assistant_buffer += head
                    stream_mode_locked = True
                    yield f"data: {json.dumps({'role': 'assistant', 'content': head})}\n\n"
                else:
                    assistant_buffer += chunk
                    yield f"data: {json.dumps({'role': 'assistant', 'content': chunk})}\n\n"
                continue

            tool_buffer += chunk
            json_str = tool_buffer.strip("`")

            try:
                if json_str.startswith("json"):
                    json_str = json_str[4:].strip()
                tool_json = json.loads(json_str)
            except json.JSONDecodeError:
                continue

            if tool_json.get("tool_name") == "job_search_topn":
                yield f"data: {json.dumps({'role': 'tool', 'status': 'runnings', 'tool_name': 'job_search_topn', 'content': tool_json['tool_params']['query']})}\n\n"
                tool_result = await job_search_topn(
                    tool_json["tool_params"]["query"],
                    int(tool_json["tool_params"]["topn"]),
                )
                print(f"job_search_topn: {tool_result}")
                yield f"data: {json.dumps({'role': 'tool', 'status': 'success', 'tool_name': 'job_search_topn', 'content': tool_json['tool_params']['query']})}\n\n"

                messages.append(
                    {
                        "role": "assistant",
                        "content": f"[TOOL_CALL]\n```json\n{json_str}\n```",
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": f"[TOOL_CALL] job_search_topn tool output: {json.dumps(tool_result, ensure_ascii=False)}",
                    }
                )

                model_stream = stream_model(messages)

            tool_buffer = ""
            head = ""
            assistant_buffer = ""
            in_tool_call = False
            stream_mode_locked = False

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/history")
async def get_session_history(
    page_size: int = 10,
    oldest_id: str = None,
    current_user=Depends(get_current_user),
    rds=Depends(get_redis),
    mongo=Depends(get_mongo),
):
    uid = current_user.uid
    redis_key = f"{uid}:session"
    session_id = await rds.get(redis_key)
    if not session_id:
        return {"error": "会话不存在"}
    if oldest_id:
        oldest_id = ObjectId(oldest_id)
    messages = await load_all_messages(mongo, session_id, page_size, oldest_id)
    for message in messages:
        message["_id"] = str(message["_id"])
    return {"session_id": session_id, "messages": messages}


@router.get("/list")
async def list_sessions(
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.uid

    total_result = await db.execute(
        select(func.count()).select_from(Session).where(Session.uid == uid)
    )
    total = total_result.scalar()

    offset = (page - 1) * page_size
    query = (
        select(Session)
        .where(Session.uid == uid)
        .order_by(Session.create_time.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.stream(query)

    sessions = []
    async for row in result:
        session = row[0]
        sessions.append(
            {
                "id": session.sid,
                "title": session.session_name,
                "create_time": session.create_time,
            }
        )

    return {"page": page, "page_size": page_size, "total": total, "sessions": sessions}


@router.get("/title")
async def get_session_title(
    session_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.uid
    session = await db.scalar(
        select(Session).where(Session.sid == session_id, Session.uid == uid)
    )
    if not session:
        return {"error": "会话不存在"}
    return {"session_id": session_id, "title": session.session_name}


@router.post("/preload")
async def preload_session(
    session_id: str,
    current_user=Depends(get_current_user),
    x_session_id: str = Header(None),
    db: AsyncSession = Depends(get_db),
    rds=Depends(get_redis),
    mongo=Depends(get_mongo),
):
    session = await db.scalar(select(Session).where(Session.sid == session_id))
    if not session:
        return {"error": "会话不存在"}
    uid = current_user.uid
    redis_key = f"{uid}:session"
    await rds.set(redis_key, session_id, ex=7 * 24 * 60 * 60)
    messages = [{"role": "system", "content": MAIN_SYSTEM_PROMPT}]
    loads_messages = await load_messages(mongo, session_id)
    messages.extend(loads_messages)
    messages_key = f"session:{session_id}:messages"
    await rds.set(
        messages_key, json.dumps(messages, ensure_ascii=False), ex=24 * 60 * 60
    )
    return {"session_id": session_id, "session_name": session.session_name}
