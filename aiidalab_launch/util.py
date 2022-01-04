#!/usr/bin/env python
# -*- coding: utf-8 -*-
from contextlib import contextmanager
from textwrap import wrap
from threading import Event, Thread, Timer

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
        if msg:
            click.echo(f"{msg.rstrip()} ", nl=False, err=True)
        with click_spinner.spinner():
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
