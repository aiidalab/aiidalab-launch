#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum, auto
from pathlib import Path
from secrets import token_hex
from typing import List, Optional
from uuid import uuid4

import docker
import toml

from .util import Timeout, wait_for_services

MAIN_PROFILE_NAME = "default"

CONTAINER_PREFIX = "aiidalab_"

DEFAULT_PORT = 8888

APPLICATION_ID = "org.aiidalab.aiidalab_launch"

LOGGER = logging.getLogger(APPLICATION_ID.split(".")[-1])


def _default_home_mount():
    return str(Path.home().joinpath("aiidalab"))


def _default_port():  # explicit function required to enable test patching
    return DEFAULT_PORT


@dataclass
class Profile:
    name: str = MAIN_PROFILE_NAME
    port: Optional[int] = field(default_factory=_default_port)
    default_apps: List[str] = field(default_factory=lambda: ["aiidalab-widgets-base"])
    system_user: str = "aiida"
    image: str = "aiidalab/aiidalab-docker-stack:latest"
    home_mount: Optional[str] = field(default_factory=lambda: _default_home_mount())

    def container_name(self):
        return f"{CONTAINER_PREFIX}{self.name}"

    def environment(self, jupyter_token):
        return {
            "AIIDALAB_DEFAULT_APPS": " ".join(self.default_apps),
            "JUPYTER_TOKEN": str(jupyter_token),
            "SYSTEM_USER": self.system_user,
        }

    def dumps(self):
        return toml.dumps({k: v for k, v in asdict(self).items() if k != "name"})

    @classmethod
    def loads(cls, name, s):
        return cls(name=name, **toml.loads(s))


@dataclass
class Config:
    profiles: List[Profile] = field(default_factory=lambda: [Profile()])
    default_profile: str = MAIN_PROFILE_NAME

    @classmethod
    def loads(cls, blob):
        config = toml.loads(blob)
        config["profiles"] = [
            Profile(name=name, **profile)
            for name, profile in config.pop("profiles", dict()).items()
        ]
        return cls(**config)

    def dumps(self):
        config = asdict(self)
        config["profiles"] = {
            profile.pop("name"): profile for profile in config.pop("profiles", [])
        }
        return toml.dumps(config)

    @classmethod
    def load(cls, path):
        return cls.loads(path.read_text())

    def save(self, path, safe=True):
        path.parent.mkdir(exist_ok=True)
        if safe:
            path_tmp = path.with_suffix(f".{uuid4()!s}")
            path_tmp.write_text(self.dumps())
            path_tmp.replace(path)
        else:
            path.write_text(self.dumps())

    def get_profile(self, name):
        for profile in self.profiles:
            if profile.name == name:
                return profile
        raise ValueError(f"Did not find profile with name '{name}'.")


@dataclass
class AiidaLabInstance:
    class AiidaLabInstanceStatus(Enum):
        UNKNOWN = auto()
        CREATED = auto()
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

    @property
    def _mounts(self):
        return (
            [
                docker.types.Mount(
                    target=f"/home/{self.profile.system_user}",
                    source=self.profile.home_mount,
                    type="bind",
                )
            ]
            if self.profile.home_mount
            else []
        )

    def pull(self):
        try:
            image = self.client.images.pull(self.profile.image)
            LOGGER.info(f"Pulled image: {image}")
        except docker.errors.ImageNotFound:
            raise RuntimeError(f"Unable to pull image: {self.profile.image}")

    def start(self):
        if self.profile.home_mount:
            LOGGER.info(f"Ensure home mount point ({self.profile.home_mount}) exists.")
            Path(self.profile.home_mount).mkdir(exist_ok=True)
        LOGGER.info(f"Starting container '{self.profile.container_name}'...")

        container = self.client.containers.run(
            image=self.profile.image,
            name=self.profile.container_name(),
            environment=self.profile.environment(jupyter_token=token_hex(32)),
            mounts=self._mounts,
            ports={"8888/tcp": self.profile.port},
            detach=True,
            remove=True,
        )
        LOGGER.info(f"Started container: {container.name} ({container.id}).")

    def restart(self, timeout=None):
        self.container().restart()

    def stop(self, timeout=None):
        try:
            self.container().stop(timeout=timeout)
        except AttributeError:
            raise RuntimeError("no container")

    def remove(self):
        try:
            self.container().remove()
        except AttributeError:
            raise RuntimeError("no container")

    def logs(self, stream=False, follow=False):
        container = self.container()
        if container is None:
            raise RuntimeError("Instance was not created.")
        return container.logs(stream=stream, follow=follow)

    def exec_create(self, cmd, privileged=False):
        LOGGER.info(f"Executing: {' '.join(cmd)}")
        return self.client.api.exec_create(
            self.container().id,
            cmd,
            user=None if privileged else self.profile.system_user,
            workdir=None if privileged else f"/home/{self.profile.system_user}",
        )["Id"]

    def wait_for_services(self, timeout=None):
        container = self.container()
        if container is None:
            raise RuntimeError("Instance was not created.")

        LOGGER.info(f"Waiting for services to come up ({container.id})...")
        start = time.time()
        wait_for_services(container, timeout=timeout)
        stop = time.time()
        if stop - start > 2:
            # It is likely that the server *just* started up, wait a few more
            # seconds, otherwise trying to access the instance right away  will
            # likely fail.
            time.sleep(5)
        LOGGER.info(f"Services are up ({container.id}).")

    def status(self, timeout=3) -> AiidaLabInstanceStatus:
        container = self.container()
        if container and container.status == "running":
            try:
                self.wait_for_services(timeout=timeout)
            except Timeout:
                return self.AiidaLabInstanceStatus.STARTING
            except RuntimeError:
                return self.AiidaLabInstanceStatus.UNKNOWN
            else:
                return self.AiidaLabInstanceStatus.UP
        elif container and container.status == "created":
            return self.AiidaLabInstanceStatus.CREATED
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
        if self.status() is not self.AiidaLabInstanceStatus.UP:
            raise RuntimeError("Cannot generate url for instance that is not up.")
        host_port = self.host_port()
        jupyter_token = self.jupyter_token()
        return f"http://localhost:{host_port}/?token={jupyter_token}"
