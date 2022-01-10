#!/usr/bin/env python
# -*- coding: utf-8 -*-
# __future__ import needed for classmethod factory functions; should be dropped
# with py 3.10.
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from enum import Enum, auto
from pathlib import Path
from secrets import token_hex
from typing import Any, AsyncGenerator, Generator, List, Optional, Union
from uuid import uuid4

import docker
import toml

from .util import _async_wrap_iter

MAIN_PROFILE_NAME = "default"

CONTAINER_PREFIX = "aiidalab_"

DEFAULT_PORT = 8888

APPLICATION_ID = "org.aiidalab.aiidalab_launch"

LOGGER = logging.getLogger(APPLICATION_ID.split(".")[-1])


def _default_home_mount() -> str:
    return str(Path.home().joinpath("aiidalab"))


def _default_port() -> int:  # explicit function required to enable test patching
    return DEFAULT_PORT


@dataclass
class Profile:
    name: str = MAIN_PROFILE_NAME
    port: Optional[int] = field(default_factory=_default_port)
    default_apps: List[str] = field(default_factory=lambda: ["aiidalab-widgets-base"])
    system_user: str = "aiida"
    image: str = "aiidalab/aiidalab-docker-stack:latest"
    home_mount: Optional[str] = field(default_factory=lambda: _default_home_mount())

    def container_name(self) -> str:
        return f"{CONTAINER_PREFIX}{self.name}"

    def environment(self, jupyter_token: str) -> dict:
        return {
            "AIIDALAB_DEFAULT_APPS": " ".join(self.default_apps),
            "JUPYTER_TOKEN": str(jupyter_token),
            "SYSTEM_USER": self.system_user,
        }

    def dumps(self) -> str:
        return toml.dumps({k: v for k, v in asdict(self).items() if k != "name"})

    @classmethod
    def loads(cls, name: str, s: str) -> Profile:
        return cls(name=name, **toml.loads(s))


@dataclass
class Config:
    profiles: List[Profile] = field(default_factory=lambda: [Profile()])
    default_profile: str = MAIN_PROFILE_NAME

    @classmethod
    def loads(cls, blob: str) -> Config:
        config = toml.loads(blob)
        config["profiles"] = [
            Profile(name=name, **profile)
            for name, profile in config.pop("profiles", dict()).items()
        ]
        return cls(**config)

    def dumps(self) -> str:
        config = asdict(self)
        config["profiles"] = {
            profile.pop("name"): profile for profile in config.pop("profiles", [])
        }
        return toml.dumps(config)

    @classmethod
    def load(cls, path: Path) -> Config:
        return cls.loads(path.read_text())

    def save(self, path: Path, safe: bool = True) -> None:
        path.parent.mkdir(exist_ok=True, parents=True)
        if safe:
            path_tmp = path.with_suffix(f".{uuid4()!s}")
            path_tmp.write_text(self.dumps())
            path_tmp.replace(path)
        else:
            path.write_text(self.dumps())

    def get_profile(self, name: str) -> Profile:
        for profile in self.profiles:
            if profile.name == name:
                return profile
        raise ValueError(f"Did not find profile with name '{name}'.")


class FailedToWaitForServices(RuntimeError):
    pass


@contextmanager
def _async_logs(
    container: docker.models.containers.Container,
) -> Generator[AsyncGenerator[Any, None], None, None]:
    logs = container.logs(stream=True, follow=False)
    try:
        yield _async_wrap_iter(logs)
    finally:
        logs.close()


@dataclass
class AiidaLabInstance:
    class AiidaLabInstanceStatus(Enum):
        UNKNOWN = auto()
        CREATED = auto()
        DOWN = auto()
        UP = auto()
        EXITED = auto()
        STARTING = auto()

    client: docker.DockerClient
    profile: Profile
    _image: docker.models.images.Image = None
    _container: docker.models.containers.Container = None

    def _get_image(self) -> Optional[docker.models.images.Image]:
        try:
            return self.client.images.get(self.profile.image)
        except docker.errors.ImageNotFound:
            return None

    def _get_container(self) -> Optional[docker.models.containers.Container]:
        try:
            return self.client.containers.get(self.profile.container_name())
        except docker.errors.NotFound:
            return None

    def __post_init__(self) -> None:
        self._image = self._get_image()
        self._container = self._get_container()

    @property
    def image(self) -> Optional[docker.models.images.Image]:
        return self._image

    @property
    def container(self) -> Optional[docker.models.containers.Container]:
        return self._container

    def _requires_container(self) -> None:
        if self.container is None:
            raise RuntimeError("This function requires a container instance.")

    @property
    def _mounts(self) -> List[docker.types.Mount]:
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

    def pull(self) -> docker.models.images.Image:
        try:
            image = self.client.images.pull(self.profile.image)
            LOGGER.info(f"Pulled image: {image}")
            self._image = image
            return image
        except docker.errors.ImageNotFound:
            raise RuntimeError(f"Unable to pull image: {self.profile.image}")

    def _ensure_home_mount_exists(self) -> None:
        if self.profile.home_mount:
            LOGGER.info(f"Ensure home mount point ({self.profile.home_mount}) exists.")
            Path(self.profile.home_mount).mkdir(exist_ok=True)

    def create(self) -> docker.models.containers.Container:
        assert self._container is None
        self._ensure_home_mount_exists()
        self._container = self.client.containers.create(
            image=(self.image or self.pull()),
            name=self.profile.container_name(),
            environment=self.profile.environment(jupyter_token=token_hex(32)),
            mounts=self._mounts,
            ports={"8888/tcp": self.profile.port},
        )
        return self._container

    def start(self) -> None:
        self._ensure_home_mount_exists()
        LOGGER.info(f"Starting container '{self.profile.container_name()}'...")
        (self.container or self.create()).start()
        assert self.container is not None
        LOGGER.info(f"Started container: {self.container.name} ({self.container.id}).")

    def restart(self) -> None:
        self._requires_container()
        assert self.container is not None
        self.container.restart()

    def stop(self, timeout: Optional[float] = None) -> None:
        self._requires_container()
        assert self.container is not None
        try:
            self.container.stop(timeout=timeout)
        except AttributeError:
            raise RuntimeError("no container")

    def remove(self) -> None:
        self._requires_container()
        assert self.container is not None
        try:
            self.container.remove()
            self._container = None
        except AttributeError:
            raise RuntimeError("no container")

    def logs(
        self, stream: bool = False, follow: bool = False
    ) -> Union[docker.types.daemon.CancellableStream, str]:
        if self.container is None:
            raise RuntimeError("Instance was not created.")
        return self.container.logs(stream=stream, follow=follow)

    def exec_create(self, cmd: str, privileged: bool = False) -> str:
        LOGGER.info(f"Executing: {' '.join(cmd)}")
        if self.container is None:
            raise RuntimeError("Instance was not created.")

        try:
            return self.client.api.exec_create(
                self.container.id,
                cmd,
                user=None if privileged else self.profile.system_user,
                workdir=None if privileged else f"/home/{self.profile.system_user}",
            )["Id"]
        except docker.errors.APIError:
            raise RuntimeError(
                f"Unable to send command to container '{self.container.id}'."
            )

    async def _wait_for_services(self) -> None:
        if self.container is None:
            raise RuntimeError("Instance was not created.")

        loop = asyncio.get_event_loop()
        LOGGER.info(f"Waiting for services to come up ({self.container.id})...")

        wait_for_services = loop.run_in_executor(
            None, self.container.exec_run, "wait-for-services"
        )

        async def _echo_logs() -> None:
            assert self.container is not None
            with _async_logs(self.container) as logs:
                async for chunk in logs:
                    if logging.DEBUG < LOGGER.getEffectiveLevel() < logging.ERROR:
                        # For 'intermediate' verbosity, echo directly to STDOUT.
                        print(chunk.decode("utf-8").strip())
                    else:
                        # Otherwise, echo to the debug log.
                        LOGGER.debug(
                            f"{self.container.id}: {chunk.decode('utf-8').strip()}"
                        )

        echo_logs = asyncio.create_task(_echo_logs())  # start logging
        result = await wait_for_services
        echo_logs.cancel()

        if result.exit_code != 0:
            LOGGER.info(f"Failed to wait for services ({self.container.id}).")
            raise FailedToWaitForServices
        else:
            LOGGER.info(f"Services are up ({self.container.id}).")

    def wait_for_services(self, timeout: Optional[float] = None) -> None:
        start = time.time()
        try:
            asyncio.run(asyncio.wait_for(self._wait_for_services(), timeout))
        except asyncio.TimeoutError:
            raise TimeoutError
        stop = time.time()
        if stop - start > 2:
            # It is likely that the server *just* started up, wait a few more
            # seconds, otherwise trying to access the instance right away  will
            # likely fail.
            time.sleep(5)

    def status(self, timeout: Optional[float] = 3.0) -> AiidaLabInstanceStatus:
        if self.container:
            self.container.reload()
            if self.container.status == "running":
                try:
                    self.wait_for_services(timeout=timeout)
                except TimeoutError:
                    return self.AiidaLabInstanceStatus.STARTING
                except RuntimeError:
                    return self.AiidaLabInstanceStatus.UNKNOWN
                else:
                    return self.AiidaLabInstanceStatus.UP
            elif self.container.status == "created":
                return self.AiidaLabInstanceStatus.CREATED
            elif self.container and self.container.status == "exited":
                return self.AiidaLabInstanceStatus.EXITED
        return self.AiidaLabInstanceStatus.DOWN

    def jupyter_token(self) -> Optional[str]:
        if self.container:
            result = self.container.exec_run("/bin/sh -c 'echo $JUPYTER_TOKEN'")
            if result.exit_code == 0:
                return result.output.decode().strip()
        return None

    def host_port(self) -> Optional[int]:
        if self.container:
            try:
                return self.container.ports["8888/tcp"][0]["HostPort"]
            except (KeyError, IndexError):
                pass
        return None

    def url(self) -> str:
        if self.status() is not self.AiidaLabInstanceStatus.UP:
            raise RuntimeError("Cannot generate url for instance that is not up.")
        host_port = self.host_port()
        jupyter_token = self.jupyter_token()
        return f"http://localhost:{host_port}/?token={jupyter_token}"
