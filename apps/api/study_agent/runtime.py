"""Event-loop factory for Windows psycopg async checkpoint compatibility."""

import asyncio
import sys


def create_event_loop() -> asyncio.AbstractEventLoop:
    """Use Selector on Windows; psycopg cannot use the default Proactor loop."""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()
