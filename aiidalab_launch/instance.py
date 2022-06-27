# __future__ import needed for classmethod factory functions; should be dropped
# with py 3.10.
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path, PurePosixPath
from secrets import token_hex
from shutil import rmtree
from time import time
from typing import Any, AsyncGenerator, Generator

import docker
from docker.models.containers import Container

from .core import LOGGER
from .profile import Profile
from .util import _async_wrap_iter, docker_mount_for, get_docker_env


def _get_host_ports(container: Container) -> Generator[int, None, None]:
    try:
        ports = container.attrs["NetworkSettings"]["Ports"]
        yield from (int(i["HostPort"]) for i in ports["8888/tcp"])
    except KeyError:
        pass


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

    def _requires_container(self) -> Container:
        container = self.container
        if container is None:
            raise RequiresContainerInstance
        return container

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

    def _extra_mount(self, extra_mount: str) -> docker.types.Mount:
        source_path, target_path, mode = self.profile.parse_extra_mount(extra_mount)
        return docker.types.Mount(
            target=str(target_path),
            source=str(source_path),
            read_only=True if mode == "ro" else False,
            type="bind" if source_path.is_absolute() else "volume",
        )

    def _mounts(self) -> Generator[docker.types.Mount, None, None]:
        yield self._conda_mount()
        if self.profile.home_mount:
            yield self._home_mount()
        for extra_mount in self.profile.extra_mounts:
            yield self._extra_mount(extra_mount)

    def configuration_changes(self) -> Generator[str, None, None]:
        self._requires_container()
        assert self.container is not None
        assert self.image is not None

        if self.container.image.id != self.image.id:
            yield "Image has changed."

        try:
            for mount in self._mounts():
                if (
                    str(docker_mount_for(self.container, mount["Target"]))
                    != mount["Source"]
                ):
                    raise ValueError
        except ValueError:
            yield "Mount configuration has changed."

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
            image=(self.image or self.pull()),
            name=self.profile.container_name(),
            environment=self.profile.environment(jupyter_token=token_hex(32)),
            mounts=list(self._mounts()),
            ports={"8888/tcp": self.profile.port},
        )
        return self._container

    def recreate(self) -> None:
        self._requires_container()
        assert self.container is not None
        self.remove()
        self.create()

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
        LOGGER.debug("Run post-start commands.")

        LOGGER.debug("Ensure ~/.conda directory is owned by the system user.")
        exit_code, _ = self.container.exec_run(
            f"chown -R 1000:1000 /home/{self.profile.system_user}/.conda",
            privileged=True,
        )
        if exit_code != 0:
            LOGGER.warn(
                "Failed to ensure ~/.conda directory is owned by the system user."
            )
        LOGGER.debug("The ~/.conda directory is owned by the system user.")

    def stop(self, timeout: float | None = None) -> None:
        self._requires_container()
        assert self.container is not None
        try:
            self.container.stop(timeout=timeout)
        except AttributeError:
            raise RuntimeError("no container")

    def remove(self, conda: bool = False, data: bool = False) -> None:
        # Remove container
        if self.container:
            self.container.remove()
            self._container = None

        # Remove conda volume
        if conda:
            try:
                self.client.volumes.get(self.profile.conda_volume_name()).remove()
            except docker.errors.NotFound:  # already removed
                LOGGER.debug(
                    f"Failed to remove conda volume '{self.profile.conda_volume_name()}', likely already removed."
                )
            except Exception as error:  # unexpected error
                raise RuntimeError(f"Failed to remove conda volume: {error}")

        if data and self.profile.home_mount:
            # Remove home volume
            home_mount_path = PurePosixPath(self.profile.home_mount)
            try:
                if home_mount_path.is_absolute():
                    rmtree(home_mount_path)
                else:
                    self.client.volumes.get(str(home_mount_path)).remove()
            except docker.errors.NotFound:
                pass  # already removed
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

    @staticmethod
    async def _init_scripts_finished(container: Container) -> None:
        loop = asyncio.get_event_loop()
        LOGGER.debug("Waiting for init services to finish...")
        result = await loop.run_in_executor(
            None, container.exec_run, "wait-for-services"
        )
        if result.exit_code != 0:
            raise FailedToWaitForServices(
                "Failed to check for init processes to complete."
            )
        LOGGER.debug("Init services finished.")

    @staticmethod
    async def _notebook_service_online(container: Container) -> None:
        loop = asyncio.get_event_loop()
        LOGGER.debug("Waiting for notebook service to become reachable...")
        while True:
            try:
                LOGGER.debug("Curl notebook...")
                result = await loop.run_in_executor(
                    None,
                    container.exec_run,
                    "curl --fail-early --fail --silent --max-time 1.0 http://localhost:8888",
                )
                if result.exit_code == 0:
                    LOGGER.debug("Notebook service reachable.")
                    return  # jupyter is online
                elif result.exit_code in (7, 28):
                    await asyncio.sleep(2)  # jupyter not yet reachable
                    continue
                else:
                    raise FailedToWaitForServices("Failed to reach notebook service.")
            except docker.errors.APIError:
                LOGGER.error("Failed to reach notebook service. Aborting.")
                raise FailedToWaitForServices(
                    "Failed to reach notebook service (unable to reach container."
                )

    @staticmethod
    async def _host_port_assigned(container: Container) -> None:
        LOGGER.debug("Waiting for host port to be assigned...")
        while True:
            container.reload()
            if any(_get_host_ports(container)):
                LOGGER.debug("Host port assigned.")
                break
            await asyncio.sleep(1)

    async def wait_for_services(self) -> None:
        container = self._requires_container()
        LOGGER.info(f"Waiting for services to come up ({container.id})...")
        start = time()
        await asyncio.gather(
            self._init_scripts_finished(container),
            self._notebook_service_online(container),
            self._host_port_assigned(container),
        )
        LOGGER.info(
            f"Services came up after {time() - start:.1f} seconds ({container.id})."
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
            jupyter_token = get_docker_env(self.container, "JUPYTER_TOKEN")
            return f"http://localhost:{host_ports[0]}/?token={jupyter_token}"
        else:
            raise NoHostPortAssigned(self.container.id)
