# -*- coding: utf-8 -*-
# @Time    : 2025/12/14 18:14:43
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : data.py
# @License : Apache-2.0
# @Desc    : 数据服务

from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime
from bson import ObjectId
from datetime import timezone


async def increment_save_chat_history(
    mongo: AsyncIOMotorDatabase, session_id: str, role: str, content: str
) -> bool:
    """
    增量保存聊天记录
    Args:
        mongo (AsyncIOMotorDatabase): MongoDB数据库连接
        session_id (str): 会话ID
        role (str): 角色(用户/助手)
        content (str): 消息内容
    Returns:
        bool: 是否成功保存
    """
    try:
        doc = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "is_compress": False,
            "created_at": datetime.now(timezone.utc),
        }
        await mongo.chat_messages.insert_one(doc)
        return True
    except Exception as e:
        print(f"increment_save_chat_history error: {e}")
        return False


async def save_compress_data(
    mongo: AsyncIOMotorDatabase, session_id: str, compress_data: str
) -> bool:
    """
    保存压缩数据
    Args:
        mongo (AsyncIOMotorDatabase): MongoDB数据库连接
        session_id (str): 会话ID
        compress_data (str): 压缩数据
    Returns:
        bool: 是否成功保存
    """
    try:
        doc = {
            "session_id": session_id,
            "role": "user",
            "content": compress_data,
            "is_compress": True,
            "created_at": datetime.now(timezone.utc),
        }
        await mongo.chat_messages.insert_one(doc)
        return True
    except Exception as e:
        print(f"save_compress_data error: {e}")
        return False


async def save_messages(
    mongo: AsyncIOMotorDatabase, session_id: str, messages: list[dict]
) -> bool:
    """
    保存聊天记录
    Args:
        mongo (AsyncIOMotorDatabase): MongoDB数据库连接
        session_id (str): 会话ID
        messages (list[dict]): 聊天记录列表[{'role': '用户', 'content': '内容'}]
    Returns:
        bool: 是否成功保存
    """
    if not messages:
        return False
    try:
        docs = []
        docs.extend(
            {
                "session_id": session_id,
                "role": msg["role"],
                "content": msg["content"],
                "is_compress": msg.get("is_compress", False),
                "created_at": datetime.now(timezone.utc),
            }
            for msg in messages
        )
        await mongo.chat_messages.insert_many(docs)
        return True
    except Exception as e:
        print(f"save_messages error: {e}")
        return False


async def load_messages(mongo: AsyncIOMotorDatabase, session_id: str) -> list[dict]:
    """
    加载聊天记录(从尾部加载, 知道碰到第一个压缩数据截止)
    Args:
        mongo (AsyncIOMotorDatabase): MongoDB数据库连接
        session_id (str): 会话ID
    Returns:
        list[dict]: 聊天记录列表[{'role': '用户', 'content': '内容'}], 注, 压缩数据的role为user, content为压缩数据
    """
    try:
        result = []

        cursor = mongo.chat_messages.find({"session_id": session_id}).sort(
            "created_at", -1
        )

        async for msg in cursor:
            result.append(
                {
                    "role": msg["role"],
                    "content": msg["content"],
                    "is_compress": msg.get("is_compress", False),
                }
            )
            if msg.get("is_compress"):
                break

        if result:
            first = result[0]
            if first["role"] == "user" and not first["is_compress"]:
                result = result[1:]

        return [{"role": m["role"], "content": m["content"]} for m in result[::-1]]

    except Exception as e:
        print(f"load_messages error: {e}")
        return []


async def load_all_messages(
    mongo: AsyncIOMotorDatabase,
    session_id: str,
    page_size: int = 10,
    oldest_id: Optional[ObjectId] = None,
) -> list[dict]:
    """
    加载所有聊天记录
    Args:
        mongo (AsyncIOMotorDatabase): MongoDB数据库连接
        session_id (str): 会话ID
        page_size (int, optional): 每页数量. Defaults to 10.
        oldest_id (Optional[ObjectId], optional): 最早消息ID. Defaults to None.
    Returns:
        list[dict]: 聊天记录列表[{'role': '用户', 'content': '内容', '_id': ObjectId}]
    """
    try:
        query = {"session_id": session_id, "is_compress": {"$ne": True}}

        if oldest_id:
            query["_id"] = {"$lt": oldest_id}

        cursor = mongo.chat_messages.find(query).sort("created_at", -1).limit(page_size)

        result = []
        async for msg in cursor:
            result.append(
                {
                    "role": msg["role"],
                    "content": msg["content"],
                    "_id": msg["_id"],
                    "is_compress": msg.get("is_compress", False),
                }
            )

        if oldest_id is None and result:
            first = result[0]
            if first["role"] == "user" and not first["is_compress"]:
                result = result[1:]

        return [
            {"role": m["role"], "content": m["content"], "_id": m["_id"]}
            for m in result[::-1]
        ]

    except Exception as e:
        print(f"load_all_messages error: {e}")
        return []
