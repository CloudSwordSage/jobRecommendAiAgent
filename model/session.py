# -*- coding: utf-8 -*-
# @Time    : 2025/11/15 11:32:50
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : session.py
# @License : Apache-2.0
# @Desc    : 会话id记录模型

from sqlalchemy import Column, Integer, String, Boolean, Enum, select, ForeignKey
from sqlalchemy.sql import expression
from sqlalchemy.ext.asyncio import AsyncSession
from .base import Base


class Session(Base):
    __tablename__ = "session"

    sid = Column(String(50), primary_key=True, index=True, nullable=False)
    uid = Column(Integer, ForeignKey("user.uid"), nullable=False)
    session_name = Column(String(50), nullable=True)
    create_time = Column(
        Integer,
        nullable=False,
        server_default=expression.text("UNIX_TIMESTAMP()"),
    )