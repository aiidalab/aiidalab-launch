#!/usr/bin/env python
# -*- coding: utf-8 -*-
from dataclasses import dataclass
from enum import Enum, auto
from textwrap import wrap
from threading import Thread
from typing import Optional

import click
import docker

from .core import Profile

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


def get_container(client, container_name):
    try:
        return client.containers.get(container_name)
    except docker.errors.NotFound:
        raise click.ClickException(
            "Unable to communicate with the AiiDAlab container with name "
            f"'{container_name}'. Is it running? Use `start` to start it."
        )


class Timeout(Exception):
    pass


def _wait_for_services(container, timeout=None):
    error = False

    def _internal():
        nonlocal error
        error = container.exec_run("wait-for-services").exit_code != 0

    thread = Thread(target=_internal)
    thread.start()
    thread.join(timeout=timeout)
    if error:
        raise RuntimeError(
            "Failed to wait-for-services, is this a valid AiiDAlab instance?"
        )
    elif thread.is_alive():
        raise Timeout


@dataclass
class AiidaLabInstance:
    class AiidaLabInstanceStatus(Enum):
        UNKNOWN = auto()
        DOWN = auto()
        UP = auto()
        STARTING = auto()

    client: docker.DockerClient
    profile: Profile

    def container(self):
        try:
            return self.client.containers.get(self.profile.container_name())
        except docker.errors.NotFound:
            return None

    def status(self) -> AiidaLabInstanceStatus:
        container = self.container()
        if container and container.status == "running":
            try:
                _wait_for_services(container, timeout=3)
            except Timeout:
                return self.AiidaLabInstanceStatus.STARTING
            except RuntimeError:
                return self.AiidaLabInstanceStatus.UNKNOWN
            else:
                return self.AiidaLabInstanceStatus.UP
        return self.AiidaLabInstanceStatus.DOWN

    def jupyter_token(self) -> Optional[str]:
        container = self.container()
        if container:
            result = container.exec_run("/bin/sh -c 'echo $JUPYTER_TOKEN'")
            if result.exit_code == 0:
                return result.output.decode().strip()
            else:
                return None

    def host_port(self) -> Optional[int]:
        container = self.container()
        if container:
            try:
                return container.ports["8888/tcp"][0]["HostPort"]
            except (KeyError, IndexError):
                return None

    def url(self) -> str:
        if not self.status() is self.AiidaLabInstanceStatus.UP:
            raise RuntimeError("Cannot generate url for instance that is not up.")
        host_port = self.host_port()
        jupyter_token = self.jupyter_token()
        return f"http://localhost:{host_port}/?token={jupyter_token}"
