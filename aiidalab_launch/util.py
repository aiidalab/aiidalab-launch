# -*- coding: utf-8 -*-
import asyncio
import logging
import webbrowser
from contextlib import contextmanager
from textwrap import wrap
from threading import Event, Thread, Timer
from typing import Any, AsyncGenerator, Generator, Iterable, Optional

import click
import click_spinner
import docker
import requests
from packaging.version import Version, parse
from requests_cache import CachedSession

MSG_UNABLE_TO_COMMUNICATE_WITH_CLIENT = (
    "Unable to communicate with docker on this host. This error usually indicates "
    "that Docker is either not installed on this system, that the docker service is "
    "not started, or that the installation is ill-configured.  Please follow the "
    "instructions at https://docs.docker.com/get-docker/ to install and start "
    "docker."
)


SESSION = CachedSession(
    "http_cache",
    backend="sqlite",
    use_cache_dir=True,
    expire_after=3600,  # 1hr
    stale_if_error=True,
)


@contextmanager
def spinner(
    msg: str = None, final: str = None, delay: float = 0
) -> Generator[None, None, None]:
    """Display spinner only after an optional initial delay."""

    def spin() -> None:
        if msg:
            click.echo(f"{msg.rstrip()} ", nl=False, err=True)
        with click_spinner.spinner():  # type: ignore
            stop.wait()
        click.echo(
            (final or "done.") if (completed.is_set() and msg) else " ", err=True
        )

    stop = Event()
    completed = Event()
    timed_spinner = Timer(delay, spin)
    timed_spinner.start()
    try:
        yield
        # Try to cancel the timer if still possible.
        timed_spinner.cancel()
        # Set the completed event since there was no exception, indicating that
        # the waited on operation completed successfully.
        completed.set()
    finally:
        stop.set()
        timed_spinner.join()


def get_docker_client(*args, **kwargs) -> docker.client.DockerClient:
    try:
        with spinner("Connecting to docker host...", delay=0.2):
            return docker.from_env(*args, **kwargs)
    except docker.errors.DockerException as error:
        click.secho(
            "\n".join(wrap(MSG_UNABLE_TO_COMMUNICATE_WITH_CLIENT)),
            fg="yellow",
            err=True,
        )
        raise click.ClickException(f"Failed to communicate with Docker client: {error}")


def webbrowser_available() -> bool:
    """Check whether a webbrowser is available.

    Useful to provide more targeted user feedback, e.g., when AiiDAlab is
    executed on a headless node via ssh.
    """

    try:
        webbrowser.get()
    except webbrowser.Error:
        return False
    else:
        return True


# Adapted from: https://stackoverflow.com/a/62297994
def _async_wrap_iter(it: Iterable) -> AsyncGenerator[Any, None]:
    """Wrap blocking iterator into an asynchronous one"""
    loop = asyncio.get_event_loop()
    q: asyncio.Queue = asyncio.Queue(1)
    exception = None
    _END = object()

    async def yield_queue_items() -> AsyncGenerator[Any, None]:
        while True:
            next_item = await q.get()
            if next_item is _END:
                break
            yield next_item
        if exception is not None:
            # the iterator has raised, propagate the exception
            raise exception

    def iter_to_queue() -> None:
        nonlocal exception
        try:
            for item in it:
                # This runs outside the event loop thread, so we
                # must use thread-safe API to talk to the queue.
                asyncio.run_coroutine_threadsafe(q.put(item), loop).result()
        except Exception as e:
            exception = e
        finally:
            asyncio.run_coroutine_threadsafe(q.put(_END), loop).result()

    Thread(target=iter_to_queue).start()
    return yield_queue_items()


def get_latest_version(timeout: float = 0.1) -> Optional[Version]:
    """Determine the latest released version (on PyPI) of this tool."""
    try:
        req = SESSION.get(
            "https://pypi.python.org/pypi/aiidalab-launch/json", timeout=timeout
        )
        req.raise_for_status()
        releases = sorted(
            [
                version
                for version, release in req.json()["releases"].items()
                if not all(r["yanked"] for r in release)
            ],
            key=parse,
        )
        return parse(releases[-1]) if releases else None
    except requests.exceptions.Timeout:
        logging.debug("Timed out while requesting latest version.")
        return None
    except OSError as error:
        logging.debug(f"Error while requesting latest version: {error}")
        return None
