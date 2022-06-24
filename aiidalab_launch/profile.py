# __future__ import needed for classmethod factory functions; should be dropped
# with py 3.10.
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import quote_plus

import toml
from docker.models.containers import Container

from .util import docker_mount_for, get_docker_env, is_volume_readonly

MAIN_PROFILE_NAME = "default"

CONTAINER_PREFIX = "aiidalab_"

DEFAULT_PORT = 8888

# Regular expression for valid container and image names as of Docker version 20.10.11:
# [a-zA-Z0-9][a-zA-Z0-9_.-]+
_REGEX_VALID_IMAGE_NAMES = r"[a-zA-Z0-9][a-zA-Z0-9_.-]+"
# For profiles in addition we do not allow underscores to avoid potential issues with moving
# to a docker-compose based implementation of aiidalab-launch in the future.
_REGEX_VALID_PROFILE_NAMES = r"[a-zA-Z0-9][a-zA-Z0-9.-]+"


def _default_port() -> int:  # explicit function required to enable test patching
    return DEFAULT_PORT


_DEFAULT_IMAGE = "aiidalab/aiidalab-docker-stack:latest"


def _valid_volume_name(source: str) -> None:
    # We do not allow relative paths so if the path is not absolute,
    # we assume volume mount, whose name is restricted by Docker.
    if not Path(source).is_absolute() and not re.fullmatch(
        _REGEX_VALID_IMAGE_NAMES, source
    ):
        raise ValueError(
            f"Invalid extra mount volume name '{source}'. Use absolute path for bind mounts."
        )


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
    image: str = _DEFAULT_IMAGE
    home_mount: str | None = None
    extra_mounts: set[str] = field(default_factory=set)

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

        _valid_volume_name(self.home_mount)

        # Normalize extra mount mode to be "rw" by default
        # so that we match Docker default but are explicit.
        for extra_mount in self.extra_mounts:
            self.parse_extra_mount(extra_mount)
            if len(extra_mount.split(":")) == 2:
                self.extra_mounts.remove(extra_mount)
                self.extra_mounts.add(f"{extra_mount}:rw")

    def container_name(self) -> str:
        return f"{CONTAINER_PREFIX}{self.name}"

    def parse_extra_mount(
        self, extra_mount: str
    ) -> tuple[Path, PurePosixPath, str | None]:
        fields = extra_mount.split(":")
        if len(fields) < 2 or len(fields) > 3:
            raise ValueError(f"Invalid extra mount option '{extra_mount}'")

        source, target = fields[:2]
        _valid_volume_name(source)

        source_path, target_path = Path(source), PurePosixPath(target)
        # Unlike for home_mount, we will not auto-create missing
        # directories for extra mounts.
        if source_path.is_absolute() and not source_path.exists():
            raise ValueError(f"Directory '{source}' does not exist")

        # By default, extra mounts are writeable
        mode = fields[2] if len(fields) == 3 else "rw"
        if mode not in ("ro", "rw"):
            raise ValueError(f"Invalid extra mount mode '{mode}'")

        return source_path, target_path, mode

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
        params = toml.loads(s)
        params["extra_mounts"] = set(params["extra_mounts"])
        return cls(name=name, **params)

    @classmethod
    def from_container(cls, container: Container) -> Profile:
        profile_name = re.sub(re.escape(CONTAINER_PREFIX), "", container.name)
        if not profile_name:
            raise RuntimeError(
                f"Container {container.id} does not appear to be an AiiDAlab container."
            )

        system_user = get_docker_env(container, "SYSTEM_USER")

        image_tag = (
            _DEFAULT_IMAGE
            if _DEFAULT_IMAGE in container.image.tags
            else container.image.tags[0]
        )

        extra_destinations: list[PurePosixPath] = [
            PurePosixPath(mount["Destination"])
            for mount in container.attrs["Mounts"]
            if mount["Destination"]
            not in (f"/home/{system_user}/.conda", f"/home/{system_user}")
        ]
        extra_mounts: set[str] = set()
        for dst in extra_destinations:
            src = docker_mount_for(container, dst)
            if is_volume_readonly(container, dst):
                extra_mounts.add(":".join([str(src), str(dst), "ro"]))
            else:
                extra_mounts.add(":".join([str(src), str(dst), "rw"]))

        return Profile(
            name=profile_name,
            port=_get_configured_host_port(container),
            default_apps=_get_aiidalab_default_apps(container),
            home_mount=str(
                docker_mount_for(container, PurePosixPath("/", "home", system_user))
            ),
            image=image_tag,
            system_user=system_user,
            extra_mounts=extra_mounts,
        )
