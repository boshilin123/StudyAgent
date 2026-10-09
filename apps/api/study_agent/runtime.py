"""Event-loop factory for Windows psycopg async checkpoint compatibility."""

import asyncio
import sys


# Windows 使用 Selector 事件循环，让异步 PostgreSQL 检查点驱动正常工作。
def create_event_loop() -> asyncio.AbstractEventLoop:
    """Use Selector on Windows; psycopg cannot use the default Proactor loop."""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()
