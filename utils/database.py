# -*- coding: utf-8 -*-
# @Time    : 2025/11/15 11:27:14
# @Author  : 墨烟行(GitHub UserName: CloudSwordSage)
# @File    : database.py
# @License : Apache-2.0
# @Desc    : 数据库相关

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession as SqlAlchemyAsyncSession,
)
from sqlalchemy.orm import sessionmaker

import redis.asyncio as redis
from motor.motor_asyncio import AsyncIOMotorClient
from neo4j import AsyncGraphDatabase, AsyncSession as Neo4jAsyncSession
from sqlalchemy import text
from config.config import Config
from model.base import Base

# --- MySQL 配置 ---
mysql_url = (
    f"mysql+aiomysql://{Config.mysql_user}:{Config.mysql_password}"
    f"@{Config.mysql_host}:{Config.mysql_port}/{Config.mysql_database}"
)

# 增加 pool_size 和 overflow 支持高并发
engine = create_async_engine(
    mysql_url,
    echo=False,
    pool_size=5000,  # 常用连接数，提高到 50
    max_overflow=5000,  # 额外扩展连接数
    pool_timeout=30,  # 等待连接超时
    pool_recycle=1800,  # 防止长连接断开
)


AsyncSessionLocal = sessionmaker(
    engine, class_=SqlAlchemyAsyncSession, autoflush=False, expire_on_commit=False
)

# --- Redis 配置 ---
redis_client = redis.Redis(
    host=Config.redis_host,
    port=Config.redis_port,
    db=Config.redis_database,
    decode_responses=True,
    max_connections=10000,  # 最大连接数，避免高并发时阻塞
)

# --- MongoDB 配置 ---
mongo_uri = (
    (
        f"mongodb://{Config.mongo_user}:{Config.mongo_password}@"
        f"{Config.mongo_host}:{Config.mongo_port}/{Config.mongo_database}"
    )
    if Config.mongo_user and Config.mongo_password
    else f"mongodb://{Config.mongo_host}:{Config.mongo_port}/{Config.mongo_database}"
)

# motor 默认使用连接池，这里显式设置 maxPoolSize
mongo_client = AsyncIOMotorClient(mongo_uri, maxPoolSize=10000, minPoolSize=100)

# --- Neo4j 配置 ---
neo4j_driver = AsyncGraphDatabase.driver(
    f"neo4j://{Config.neo4j_host}:{Config.neo4j_port}",
    auth=(Config.neo4j_user, Config.neo4j_password),
    max_connection_lifetime=1800,
    max_connection_pool_size=10000,  # 高并发连接数
    connection_acquisition_timeout=30,
)


async def get_db() -> SqlAlchemyAsyncSession:
    async with AsyncSessionLocal() as db:
        yield db


async def get_redis():
    yield redis_client


async def get_mongo():
    yield mongo_client[Config.mongo_database]


async def get_neo4j() -> Neo4jAsyncSession:
    session: Neo4jAsyncSession = neo4j_driver.session()
    try:
        yield session
    finally:
        await session.close()


async def shutdown():
    await redis_client.aclose()
    mongo_client.close()
    await neo4j_driver.close()
    await engine.dispose()


async def init_db():
    import model.user
    import model.job
    import model.session

    async with engine.begin() as conn:
        # await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
        # await conn.execute(text("TRUNCATE TABLE `job`;"))
        # await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

        await conn.run_sync(Base.metadata.create_all)
