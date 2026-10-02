import asyncio
import sys

from uvicorn import Config

from study_agent.runtime import create_event_loop


def test_uvicorn_resolves_checkpoint_compatible_loop_factory():
    factory = Config(
        "study_agent.main:app", loop="study_agent.runtime:create_event_loop"
    ).get_loop_factory()
    assert factory is create_event_loop
    loop = factory()
    try:
        assert not loop.is_closed()
        if sys.platform == "win32":
            assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()
