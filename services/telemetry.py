# -*- coding: utf-8 -*-
# @Time    : 2025/11/25 15:36:47
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : telemetry.py
# @License : Apache-2.0
# @Desc    : 错误上报

from contextlib import suppress
from config import Config

try:
    import sentry_sdk
except Exception:
    sentry_sdk = None


def init_sentry() -> None:
    if Config.sentry_dsn and sentry_sdk:
        with suppress(Exception):
            sentry_sdk.init(dsn=Config.sentry_dsn, traces_sample_rate=0.05)


def capture_exception(e: BaseException) -> None:
    if sentry_sdk:
        with suppress(Exception):
            sentry_sdk.capture_exception(e)
