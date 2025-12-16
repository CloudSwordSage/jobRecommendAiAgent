# -*- coding: utf-8 -*-
# @Time    : 2025/11/15 11:26:25
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : user.py
# @License : Apache-2.0
# @Desc    : 用户模型

from typing import Optional
from sqlalchemy import Column, Integer, String, Boolean, Enum, select
from sqlalchemy.sql import expression
from sqlalchemy.ext.asyncio import AsyncSession
from .base import Base


class User(Base):
    __tablename__ = "user"

    uid = Column(
        Integer, primary_key=True, index=True, autoincrement=True, nullable=False
    )
    email = Column(String(50), index=True, nullable=False)
    username = Column(String(50), unique=True, index=True, nullable=False)
    display_name = Column(String(50), index=True, nullable=False)
    password = Column(String(255), nullable=False)
    # salt = Column(String(255), nullable=False)

    @classmethod
    async def get_by_username(cls, db: AsyncSession, username: str) -> Optional["User"]:
        result = await db.execute(select(cls).where(cls.username == username))
        return result.scalars().first()

    @classmethod
    async def get_by_uid(cls, db: AsyncSession, uid: int) -> Optional["User"]:
        result = await db.execute(select(cls).where(cls.uid == uid))
        return result.scalars().first()
