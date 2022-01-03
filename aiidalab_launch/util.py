#!/usr/bin/env python
# -*- coding: utf-8 -*-
import asyncio
from contextlib import contextmanager
from textwrap import wrap
from threading import Thread

import click
import click_spinner
import docker

MSG_UNABLE_TO_COMMUNICATE_WITH_CLIENT = (
    "Unable to communicate with docker on this host. This error usually indicates "
    "that Docker is either not installed on this system, that the docker service is "
    "not started, or that the installation is ill-configured.  Please follow the "
    "instructions at https://docs.docker.com/get-docker/ to install and start "
    "docker."
)


@contextmanager
def spinner(msg=None, final=None):
    """Display spinner with optional messaging."""
    if msg:
        click.echo(f"{msg.rstrip()} ", nl=False, err=True)
    with click_spinner.spinner():
        yield
    if msg:
        click.echo(final or "done.", err=True)


@contextmanager
def spinner_after_delay(delay, *args, **kwargs):
    """Display spinner in async context with optional initial delay."""

    async def spin_forever():
        await asyncio.sleep(delay)
        with spinner(*args, **kwargs):
            try:
                while True:  # wait forever
                    await asyncio.sleep(60)
            except asyncio.CancelledError:
                return

    spinner_ = asyncio.create_task(spin_forever())
    yield
    spinner_.cancel()


async def _get_docker_client(spinner_delay, *args, **kwargs):
    with spinner_after_delay(spinner_delay, "Connecting to docker host..."):
        return await asyncio.to_thread(docker.from_env, *args, **kwargs)


def get_docker_client(spinner_delay=0.2, *args, **kwargs):
    try:
        return asyncio.run(_get_docker_client(spinner_delay, *args, **kwargs))
    except docker.errors.DockerException as error:
        click.secho(
            "\n".join(wrap(MSG_UNABLE_TO_COMMUNICATE_WITH_CLIENT)),
            fg="yellow",
            err=True,
        )
        raise click.ClickException(f"Failed to communicate with Docker client: {error}")


def get_container(client, container_name):  # obsolete?
    try:
        return client.containers.get(container_name)
    except docker.errors.NotFound:
        raise click.ClickException(
            "Unable to communicate with the AiiDAlab container with name "
            f"'{container_name}'. Is it running? Use `start` to start it."
        )


class Timeout(Exception):
    pass


def wait_for_services(container, timeout=None):
    error = False

    def _internal():
        nonlocal error
        error = container.exec_run("wait-for-services").exit_code != 0

    thread = Thread(target=_internal, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if error:
        raise RuntimeError(
            "Failed to wait-for-services, is this a valid AiiDAlab instance?"
        )
    elif thread.is_alive():
        raise Timeout
