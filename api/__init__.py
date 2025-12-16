# -*- coding: utf-8 -*-
# @Time    : 2025/11/15 11:11:09
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : __init__.py
# @License : Apache-2.0
# @Desc    :

import os
import importlib
from fastapi import APIRouter
from .auth import router as auth_router
from .sessions import router as sessions_router

router = APIRouter(prefix="/api")

router.include_router(auth_router)
router.include_router(sessions_router)
