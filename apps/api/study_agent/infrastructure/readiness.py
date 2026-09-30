import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from minio import Minio
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from urllib3 import PoolManager, Timeout

from study_agent.config import get_settings

Probe = Callable[[], Awaitable[None]]


def get_readiness_probes() -> dict[str, Probe]:
    settings = get_settings()
    timeout = settings.readiness_timeout_seconds

    async def database() -> None:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    async def redis_check(url: str) -> None:
        client = Redis.from_url(url, socket_connect_timeout=timeout, socket_timeout=timeout)
        try:
            await client.ping()
        finally:
            await client.aclose()

    async def redis() -> None:
        await redis_check(settings.redis_url)

    async def broker() -> None:
        await redis_check(settings.celery_broker_url)

    async def milvus() -> None:
        def check() -> None:
            from pymilvus import MilvusClient

            client = MilvusClient(uri=settings.milvus_uri, timeout=timeout)
            try:
                client.list_collections(timeout=timeout)
            finally:
                client.close()

        await asyncio.to_thread(check)

    async def storage() -> None:
        def check() -> None:
            if settings.storage_backend == "local":
                root = Path(settings.local_storage_path)
                if not root.is_dir() or not os.access(root, os.R_OK | os.W_OK):
                    raise OSError("local storage unavailable")
            else:
                client = Minio(
                    settings.minio_endpoint,
                    access_key=settings.minio_access_key,
                    secret_key=settings.minio_secret_key,
                    secure=settings.minio_secure,
                    http_client=PoolManager(
                        timeout=Timeout(connect=timeout, read=timeout), retries=0
                    ),
                )
                # Fresh deployments may not have created the bucket yet.
                client.bucket_exists(settings.minio_bucket)

        await asyncio.to_thread(check)

    return {
        "postgresql": database,
        "redis": redis,
        "broker": broker,
        "milvus": milvus,
        "storage": storage,
    }
