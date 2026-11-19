import subprocess
import sys
from textwrap import dedent
from time import time

from packaging.version import parse

from aiidalab_launch.util import get_latest_version


def test_get_latest_version(mock_pypi_request):
    assert get_latest_version() == parse("2022.1010")


def test_get_latest_version_timeout(mock_pypi_request_timeout):
    start = time()
    assert get_latest_version() is None
    assert (time() - start) < 0.5


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
    )

    assert "Queue.put" not in result.stderr
