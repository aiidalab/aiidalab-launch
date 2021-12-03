#!/usr/bin/env python
# -*- coding: utf-8 -*-
from textwrap import wrap
from threading import Thread

import click
import docker

MSG_UNABLE_TO_COMMUNICATE_WITH_CLIENT = (
    "Unable to communicate with docker on this host. This error usually "
    "indicates that Docker is not actually installed on this system or that the "
    "installation is ill-configured. Please follow the instructions at "
    "https://docs.docker.com/get-docker/ to install docker."
)


def get_docker_client():
    try:
        return docker.from_env()
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
