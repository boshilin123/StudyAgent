"""Production PostgreSQL resource. Schema setup is an explicit deployment command."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from study_agent.config import get_settings
from study_agent.runtime import create_event_loop


def psycopg_connection_string(database_url: str) -> str:
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("辅导检查点需要 PostgreSQL")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@asynccontextmanager
async def open_tutor_checkpointer(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.tutor_checkpointer = None
    app.state.tutor_checkpoint_error = None
    app.state.tutor_lock_engine = None
    pool = None
    lock_engine = None
    try:
        if settings.tutor_enabled:
            lock_engine = create_async_engine(
                settings.database_url,
                pool_size=4,
                max_overflow=0,
                pool_timeout=0.1,
                pool_pre_ping=True,
            )
            app.state.tutor_lock_engine = lock_engine
            pool = AsyncConnectionPool[AsyncConnection[dict[str, Any]]](
                psycopg_connection_string(
                    settings.tutor_checkpointer_db_url or settings.database_url
                ),
                min_size=0,
                max_size=4,
                open=False,
                timeout=3,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                    "connect_timeout": 3,
                },
            )
            await pool.open()
            # Read-only probe: never implicitly create the framework tables on startup.
            async with asyncio.timeout(3):
                async with pool.connection() as connection:
                    cursor = await connection.execute(
                        "SELECT to_regclass('public.checkpoints') AS name"
                    )
                    row = await cursor.fetchone()
                    if not row or not row["name"]:
                        raise RuntimeError("checkpoint schema not initialized")
            app.state.tutor_checkpointer = AsyncPostgresSaver(pool)
    except Exception:
        app.state.tutor_checkpoint_error = "TUTOR_CHECKPOINT_UNAVAILABLE"
    try:
        yield
    finally:
        if pool:
            await pool.close()
        if lock_engine:
            await lock_engine.dispose()


async def setup_checkpointer() -> None:
    settings = get_settings()
    async with AsyncPostgresSaver.from_conn_string(
        psycopg_connection_string(settings.tutor_checkpointer_db_url or settings.database_url)
    ) as saver:
        await saver.setup()


if __name__ == "__main__":
    with asyncio.Runner(loop_factory=create_event_loop) as runner:
        runner.run(setup_checkpointer())
