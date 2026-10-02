"""Prepare only the explicitly named isolated acceptance database; print no credentials."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import sql
from sqlalchemy.engine import make_url
from study_agent.config import Settings
from study_agent.infrastructure.checkpointer import psycopg_connection_string

ROOT = Path(__file__).resolve().parents[1]
DATABASE = "study_agent_test_upgrade"


async def prepare(url: str) -> None:
    async with AsyncPostgresSaver.from_conn_string(
        psycopg_connection_string(url)
    ) as saver:
        await saver.setup()


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    settings = Settings(_env_file=ROOT / ".env")
    target = make_url(settings.database_url).set(
        host="127.0.0.1",
        port=int(os.environ.get("UPGRADE_POSTGRES_PORT", "55432")),
        database=DATABASE,
    )
    assert target.database == DATABASE
    admin = target.set(database="postgres", drivername="postgresql")
    with psycopg.connect(
        admin.render_as_string(hide_password=False), autocommit=True
    ) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname=%s", (DATABASE,)
        ).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE)))
    url = target.set(drivername="postgresql+asyncpg").render_as_string(
        hide_password=False
    )
    env = {
        **os.environ,
        "DATABASE_URL": url,
        "TEST_DATABASE_URL": url,
        "TUTOR_CHECKPOINTER_DB_URL": url,
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT / "apps" / "api",
        env=env,
        check=True,
    )
    asyncio.run(prepare(url))
    print(
        "Isolated acceptance database migrated and PostgreSQL checkpoint schema initialized."
    )
    if len(sys.argv) > 1:
        # argv contains test commands only. Sensitive values travel solely through env.
        subprocess.run(
            [sys.executable, "-m", "pytest", *sys.argv[1:]],
            cwd=ROOT / "apps" / "api",
            env=env,
            check=True,
        )


if __name__ == "__main__":
    main()
