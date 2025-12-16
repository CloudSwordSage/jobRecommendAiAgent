# -*- coding: utf-8 -*-
# @Time    : 2025/11/15 10:44:39
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : app.py
# @License : Apache-2.0
# @Desc    : FastAPI 应用入口

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from config.config import Config
from api import router as api_router
from contextlib import asynccontextmanager

from utils.database import shutdown, init_db
from services.smtp import connect_smtp, disconnect_smtp
from starlette.middleware.base import BaseHTTPMiddleware
from services.telemetry import init_sentry
from services.llm import init_llm
from MCP.vector_service import init_job_vector_service

# from services.job import start_import_jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting application...")
    await init_db()
    print("Database initialized")
    await connect_smtp()
    print("SMTP connected")
    init_llm()
    print("LLM initialized")
    init_job_vector_service()
    print("Vector service initialized")
    init_sentry()
    print("Sentry initialized")
    # await start_import_jobs()
    # print("Jobs imported")

    print("Application started")

    yield

    await shutdown()
    print("Database shutdown")
    await disconnect_smtp()
    print("SMTP disconnected")


app = FastAPI(lifespan=lifespan)


class AddClientIPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        x_forwarded_for = request.headers.get("X-Forwarded-For")
        client_ip = (
            x_forwarded_for.split(",")[0].strip()
            if x_forwarded_for
            else request.client.host
        )
        request.state.client_ip = client_ip
        return await call_next(request)


# 添加客户端IP中间件
app.add_middleware(AddClientIPMiddleware)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 包含API路由
app.include_router(api_router)


@app.get("/")
async def root():
    """
    test root
    """
    return {"message": "Hello World"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, workers=10)
