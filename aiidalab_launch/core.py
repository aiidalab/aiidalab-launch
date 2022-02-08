# __future__ import needed for classmethod factory functions; should be dropped
# with py 3.10.
from __future__ import annotations

import asyncio
import logging
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from enum import Enum, auto
from pathlib import Path, PurePosixPath
from secrets import token_hex
from shutil import rmtree
from typing import Any, AsyncGenerator, Generator
from urllib.parse import quote_plus
from uuid import uuid4

import docker
import toml
from docker.models.containers import Container
from packaging.version import parse as parse_version

from .util import _async_wrap_iter, docker_mount_for, get_docker_env
from .version import __version__

MAIN_PROFILE_NAME = "default"

CONTAINER_PREFIX = "aiidalab_"

DEFAULT_PORT = 8888

APPLICATION_ID = "org.aiidalab.aiidalab_launch"

CONFIG_VERSION = parse_version(__version__).base_version

LOGGER = logging.getLogger(APPLICATION_ID.split(".")[-1])

# Regular expression for valid container names as of Docker version 20.10.11:
# [a-zA-Z0-9][a-zA-Z0-9_.-]
# In addition we do not allow underscores to avoid potential issues with moving
# to a docker-compose based implementation of aiidalab-launch in the future.
_REGEX_VALID_PROFILE_NAMES = r"[a-zA-Z0-9][a-zA-Z0-9.-]+"


def _default_port() -> int:  # explicit function required to enable test patching
    return DEFAULT_PORT


def _get_configured_host_port(container: Container) -> int | None:
    try:
        host_config = container.attrs["HostConfig"]
        return int(host_config["PortBindings"]["8888/tcp"][0]["HostPort"]) or None
    except (KeyError, IndexError, ValueError):
        pass
    return None


def _get_host_ports(container: Container) -> Generator[int, None, None]:
    try:
        ports = container.attrs["NetworkSettings"]["Ports"]
        yield from (int(i["HostPort"]) for i in ports["8888/tcp"])
    except KeyError:
        pass


def _get_system_user(container: Container) -> str:
    return get_docker_env(container, "SYSTEM_USER")


def _get_jupyter_token(container: Container) -> str:
    return get_docker_env(container, "JUPYTER_TOKEN")


def _get_aiidalab_default_apps(container: Container) -> list:
    try:
        return get_docker_env(container, "AIIDALAB_DEFAULT_APPS").split()
    except KeyError:
        return []


@dataclass
class Profile:
    name: str = MAIN_PROFILE_NAME
    port: int | None = field(default_factory=_default_port)
    default_apps: list[str] = field(default_factory=lambda: ["aiidalab-widgets-base"])
    system_user: str = "aiida"
    image: str = "aiidalab/aiidalab-docker-stack:latest"
    home_mount: str | None = None

    def __post_init__(self):
        if (
            not re.fullmatch(_REGEX_VALID_PROFILE_NAMES, self.name)
            or quote_plus(self.name) != self.name
        ):
            raise ValueError(
                f"Invalid profile name '{self.name}'. The profile name must be "
                "composed of the following characters [a-zA-Z0-9.-] and must "
                "start with an alphanumeric character."
            )
        if self.home_mount is None:
            self.home_mount = f"{CONTAINER_PREFIX}{self.name}_home"

    def container_name(self) -> str:
        return f"{CONTAINER_PREFIX}{self.name}"

    def conda_volume_name(self) -> str:
        return f"{self.container_name()}_conda"

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

    @classmethod
    def from_container(cls, container: Container) -> Profile:
        profile_name = re.sub(re.escape(CONTAINER_PREFIX), "", container.name)
        if not profile_name:
            raise RuntimeError(
                f"Container {container.id} does not appear to be an AiiDAlab container."
            )

        system_user = _get_system_user(container)
        return Profile(
            name=profile_name,
            port=_get_configured_host_port(container),
            default_apps=_get_aiidalab_default_apps(container),
            home_mount=str(
                docker_mount_for(container, PurePosixPath("/", "home", system_user))
            ),
            image=container.image.tags[0],
            system_user=system_user,
        )


@dataclass
class Config:
    profiles: list[Profile] = field(default_factory=lambda: [Profile()])
    default_profile: str = MAIN_PROFILE_NAME

    # The configuration is always stored to disk beginning with version
    # 2022.1012, which means we assume that if no configuration is stored
    # we cannot make any assumptions about the latest applicable version.
    version: str | None = None

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


class RequiresContainerInstance(RuntimeError):
    """Raised when trying to perform operation that requires a container instance."""


class NoHostPortAssigned(RuntimeError):
    """Raised when then trying to obtain the instance URL, but there is not host port."""


@contextmanager
def _async_logs(
    container: Container,
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
    _container: Container = None

    def _get_image(self) -> docker.models.images.Image | None:
        try:
            return self.client.images.get(self.profile.image)
        except docker.errors.ImageNotFound:
            return None

    def _get_container(self) -> Container | None:
        try:
            return self.client.containers.get(self.profile.container_name())
        except docker.errors.NotFound:
            return None

    def __post_init__(self) -> None:
        self._image = self._get_image()
        self._container = self._get_container()

    @property
    def image(self) -> docker.models.images.Image | None:
        return self._image

    @property
    def container(self) -> Container | None:
        if self._container is None:
            self._container = self._get_container()
        return self._container

    def _requires_container(self) -> None:
        if self.container is None:
            raise RequiresContainerInstance

    def _conda_mount(self) -> docker.types.Mount:
        return docker.types.Mount(
            target=f"/home/{self.profile.system_user}/.conda",
            source=self.profile.conda_volume_name(),
        )

    def _home_mount(self) -> docker.types.Mount:
        assert self.profile.home_mount is not None
        home_mount_path = Path(self.profile.home_mount)
        return docker.types.Mount(
            target=f"/home/{self.profile.system_user}",
            source=self.profile.home_mount,
            type="bind" if home_mount_path.is_absolute() else "volume",
        )

    def _mounts(self) -> Generator[docker.types.Mount, None, None]:
        yield self._conda_mount()
        if self.profile.home_mount:
            yield self._home_mount()

    def configuration_changes(self) -> Generator[str, None, None]:
        self._requires_container()
        assert self.container is not None
        assert self.image is not None

        if self.container.image.id != self.image.id:
            yield "Image has changed."

        if self.profile != Profile.from_container(self.container):
            yield "Profile configuration has changed."

    def pull(self) -> docker.models.images.Image:
        try:
            image = self.client.images.pull(self.profile.image)
            LOGGER.info(f"Pulled image: {image}")
            self._image = image
            return image
        except docker.errors.NotFound:
            raise RuntimeError(f"Unable to pull image: {self.profile.image}")

    def _ensure_home_mount_exists(self) -> None:
        if self.profile.home_mount:
            home_mount_path = Path(self.profile.home_mount)
            if home_mount_path.is_absolute():
                LOGGER.info(
                    f"Ensure home mount point ({self.profile.home_mount}) exists."
                )
                home_mount_path.mkdir(exist_ok=True, parents=True)

    def create(self) -> Container:
        assert self._container is None
        self._ensure_home_mount_exists()
        self._container = self.client.containers.create(
            image=(self.image or self.pull()).attrs["RepoDigests"][0],
            name=self.profile.container_name(),
            environment=self.profile.environment(jupyter_token=token_hex(32)),
            mounts=list(self._mounts()),
            ports={"8888/tcp": self.profile.port},
        )
        return self._container

    def start(self) -> None:
        self._ensure_home_mount_exists()
        LOGGER.info(f"Starting container '{self.profile.container_name()}'...")
        (self.container or self.create()).start()
        assert self.container is not None
        LOGGER.info(f"Started container: {self.container.name} ({self.container.id}).")
        self._run_post_start()

    def restart(self) -> None:
        self._requires_container()
        assert self.container is not None
        self.container.restart()
        self._run_post_start()

    def _run_post_start(self) -> None:
        assert self.container is not None
        logging.debug("Run post-start commands.")

        logging.debug("Ensure ~/.conda directory is owned by the system user.")
        exit_code, _ = self.container.exec_run(
            f"chown -R 1000:1000 /home/{self.profile.system_user}/.conda",
            privileged=True,
        )
        if exit_code != 0:
            logging.warn(
                "Failed to ensure ~/.conda directory is owned by the system user."
            )

    def stop(self, timeout: float | None = None) -> None:
        self._requires_container()
        assert self.container is not None
        try:
            self.container.stop(timeout=timeout)
        except AttributeError:
            raise RuntimeError("no container")

    def remove(self, data: bool = False) -> None:
        # Remove container
        if self.container:
            self.container.remove()
            self._container = None

        # Remove conda volume
        try:
            self.client.volumes.get(self.profile.conda_volume_name()).remove()
        except docker.errors.NotFound:  # already removed
            logging.debug(
                f"Failed to remove conda volume '{self.profile.conda_volume_name()}', likely already removed."
            )
        except Exception as error:  # unexpected error
            raise RuntimeError(f"Failed to remove conda volume: {error}")

        if data:
            # Remove home volume
            try:
                home_mount = docker_mount_for(
                    self.container,
                    PurePosixPath("/home", _get_system_user(self.container)),
                )
                if isinstance(home_mount, Path) and home_mount.is_absolute():
                    rmtree(home_mount)
                else:
                    self.client.volumes.get(home_mount).remove()
            except Exception as error:  # unexpected error
                raise RuntimeError(f"Failed to remove home volume: {error}")

    def logs(
        self, stream: bool = False, follow: bool = False
    ) -> docker.types.daemon.CancellableStream | str:
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

    async def echo_logs(self) -> None:
        assert self.container is not None
        with _async_logs(self.container) as logs:
            async for chunk in logs:
                LOGGER.debug(f"{self.container.id}: {chunk.decode('utf-8').strip()}")

    async def _init_scripts_finished(self) -> None:
        assert self.container is not None
        loop = asyncio.get_event_loop()
        logging.info("Waiting for init services to finish...")
        result = await loop.run_in_executor(
            None, self.container.exec_run, "wait-for-services"
        )
        if result.exit_code != 0:
            raise FailedToWaitForServices(
                "Failed to check for init processes to complete."
            )

    async def _notebook_service_online(self) -> None:
        assert self.container is not None
        loop = asyncio.get_event_loop()
        logging.info("Waiting for notebook service to become reachable...")
        while True:
            result = await loop.run_in_executor(
                None,
                self.container.exec_run,
                "curl --fail-early --fail --silent --max-time 1.0 http://localhost:8888",
            )
            if result.exit_code == 0:
                return  # jupyter is online
            elif result.exit_code in (7, 28):
                await asyncio.sleep(1)  # jupyter not yet reachable
                continue
            else:
                raise FailedToWaitForServices("Failed to reach notebook service.")

    async def _host_port_assigned(self) -> None:
        container = self.container
        assert container is not None
        while True:
            container.reload()
            if any(_get_host_ports(container)):
                break
            asyncio.sleep(1)

    async def wait_for_services(self) -> None:
        if self.container is None:
            raise RuntimeError("Instance was not created.")

        LOGGER.info(f"Waiting for services to come up ({self.container.id})...")
        await asyncio.gather(
            self._init_scripts_finished(),
            self._notebook_service_online(),
            self._host_port_assigned(),
        )

    async def status(self, timeout: float | None = 5.0) -> AiidaLabInstanceStatus:
        if self.container:
            self.container.reload()
            await asyncio.sleep(0)
            if self.container.status == "running":
                try:
                    await asyncio.wait_for(self.wait_for_services(), timeout=timeout)
                except asyncio.TimeoutError:
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

    def host_ports(self) -> list[int]:
        self._requires_container()
        assert self.container is not None
        self.container.reload()
        return list(_get_host_ports(self.container))

    def url(self) -> str:
        self._requires_container()
        assert self.container is not None
        self.container.reload()
        host_ports = list(_get_host_ports(self.container))
        if len(host_ports) > 0:
            jupyter_token = _get_jupyter_token(self.container)
            return f"http://localhost:{host_ports[0]}/?token={jupyter_token}"
        else:
            raise NoHostPortAssigned(self.container.id)
