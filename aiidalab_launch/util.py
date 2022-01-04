#!/usr/bin/env python
# -*- coding: utf-8 -*-
from contextlib import contextmanager
from textwrap import wrap
from threading import Event, Thread

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
def spinner(msg=None, final=None, delay=0):
    """Display spinner only after an optional initial delay."""

    def spin():
        if not stop.wait(delay):
            if msg:
                click.echo(f"{msg.rstrip()} ", nl=False, err=True)
            with click_spinner.spinner():
                stop.wait()  # wait until stopped
            if msg:
                click.echo(final or "done.", err=True)

    stop = Event()
    thread = Thread(target=spin)
    thread.start()
    yield
    stop.set()
    thread.join()


def get_docker_client(*args, **kwargs):
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
