# __future__ import needed for classmethod factory functions; should be dropped
# with py 3.10.
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from urllib.parse import quote_plus

import toml
from docker.models.containers import Container

from .util import docker_mount_for, get_docker_env

MAIN_PROFILE_NAME = "default"

CONTAINER_PREFIX = "aiidalab_"

DEFAULT_PORT = 8888

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

        system_user = get_docker_env(container, "SYSTEM_USER")
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
