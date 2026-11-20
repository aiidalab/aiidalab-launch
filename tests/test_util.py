import asyncio
import subprocess
import sys
import threading
import time
from textwrap import dedent

import pytest
from packaging.version import parse

from aiidalab_launch.util import _async_wrap_iter, get_latest_version


def test_get_latest_version(mock_pypi_request):
    assert get_latest_version() == parse("2022.1010")


def test_get_latest_version_timeout(mock_pypi_request_timeout):
    start = time.time()
    assert get_latest_version() is None
    assert (time.time() - start) < 0.5


def test_async_wrap_iter_no_queue_put_warning_on_loop_close():
    result = subprocess.run(
        [
            sys.executable,
            "-W",
            "always",
            "-c",
            dedent(
                """
            import asyncio
            import time

            from aiidalab_launch.util import _async_wrap_iter


            def blocking_iter():
                for i in range(20):
                    time.sleep(0.01)
                    yield i


            async def main():
                wrapped = _async_wrap_iter(blocking_iter())
                await wrapped.__anext__()


            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(main())
            loop.close()
            time.sleep(0.2)
            """
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "Queue.put" not in result.stderr
    # Note: the script deliberately abandons the generator, so Python may warn
    # about its un-awaited `aclose`; only the queue-put coroutine matters here.
    assert "q.put" not in result.stderr
    assert "Traceback" not in result.stderr


def test_async_wrap_iter_early_close_stops_producer():
    closed = threading.Event()

    def blocking_iter():
        try:
            for i in range(1000):
                time.sleep(0.01)
                yield i
        finally:
            closed.set()

    async def main():
        wrapped = _async_wrap_iter(blocking_iter())
        assert await wrapped.__anext__() == 0
        await wrapped.aclose()

    asyncio.run(main())
    # Producer must notice the consumer is gone and close the source iterator.
    assert closed.wait(timeout=5)


def test_async_wrap_iter_loop_closed_with_pending_put_stops_producer():
    closed = threading.Event()

    def blocking_iter():
        try:
            yield from range(1000)
        finally:
            closed.set()

    loop = asyncio.new_event_loop()

    async def main():
        wrapped = _async_wrap_iter(blocking_iter())
        await wrapped.__anext__()

    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
    loop.close()
    assert closed.wait(timeout=5)


def test_async_wrap_iter_propagates_exception():
    def failing_iter():
        yield 1
        raise ValueError("boom")

    async def main():
        return [i async for i in _async_wrap_iter(failing_iter())]

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(main())
