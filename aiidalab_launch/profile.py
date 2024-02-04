# __future__ import needed for classmethod factory functions; should be dropped
# with py 3.10.
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import quote_plus

import docker
import toml
from docker.models.containers import Container

from .core import LOGGER
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


DEFAULT_IMAGE = "aiidalab/full-stack:latest"


def _valid_volume_name(source: str) -> None:
    # We do not allow relative paths so if the path is not absolute,
    # we assume volume mount, whose name is restricted by Docker.
    if not Path(source).is_absolute() and not re.fullmatch(
        _REGEX_VALID_IMAGE_NAMES, source
    ):
        raise docker.errors.InvalidArgument(
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


# We extend the Mount type from Docker API
# with some extra validation to fail early if user provides wrong argument.
# https://github.com/docker/docker-py/blob/bd164f928ab82e798e30db455903578d06ba2070/docker/types/services.py#L305
class ExtraMount(docker.types.Mount):
    @classmethod
    def parse_mount_string(cls, mount_str) -> docker.types.Mount:
        mount = super().parse_mount_string(mount_str)
        # For some reason, Docker API allows Source to be None??
        # Not on our watch!
        if mount["Source"] is None:
            raise docker.errors.InvalidArgument(
                f"Invalid extra mount specification '{mount}'"
            )

        # If the read-write mode is not "rw", docker assumes "ro"
        # Let's be more strict here to avoid confusing errors later.
        parts = mount_str.split(":")
        if len(parts) == 3:
            mode = parts[2]
            if mode not in ("ro", "rw"):
                raise docker.errors.InvalidArgument(
                    f"Invalid read-write mode in '{mount}'"
                )

        # Unlike for home_mount, we will not auto-create missing
        # directories for extra mounts.
        if mount["Type"] == "bind":
            source_path = Path(mount["Source"])
            if not source_path.exists():
                raise docker.errors.InvalidArgument(
                    f"Directory '{source_path}' does not exist!"
                )
        else:
            _valid_volume_name(mount["Source"])
        return mount


@dataclass
class Profile:
    name: str = MAIN_PROFILE_NAME
    port: int | None = field(default_factory=_default_port)
    default_apps: list[str] = field(default_factory=lambda: [])
    system_user: str = "jovyan"
    image: str = DEFAULT_IMAGE
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
        for extra_mount in self.extra_mounts.copy():
            mount = ExtraMount.parse_mount_string(extra_mount)
            mode = "ro" if mount["ReadOnly"] else "rw"
            if not extra_mount.endswith(mode):
                self.extra_mounts.remove(extra_mount)
                self.extra_mounts.add(f"{extra_mount}:{mode}")

        if (
            self.image.split(":")[0].endswith("aiidalab/full-stack")
            and self.system_user != "jovyan"
        ):
            # TODO: ERROR out in this case
            LOGGER.warning(
                "Resetting the system user may create issues for this image!"
            )

    def container_name(self) -> str:
        return f"{CONTAINER_PREFIX}{self.name}"

    def conda_volume_name(self) -> str:
        return f"{self.container_name()}_conda"

    def environment(self, jupyter_token: str) -> dict:
        return {
            "AIIDALAB_DEFAULT_APPS": " ".join(self.default_apps),
            "JUPYTER_TOKEN": str(jupyter_token),
            "SYSTEM_USER": self.system_user,
            "NB_USER": self.system_user,
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
            DEFAULT_IMAGE
            if DEFAULT_IMAGE in container.image.tags
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
