#!/usr/bin/env python
"""Tool to launch and manage AiiDAlab instances with docker.

Authors:
    * Carl Simon Adorf <simon.adorf@epfl.ch>
"""
from dataclasses import dataclass, field
from pathlib import Path

import click
import docker
from packaging.version import parse

from .config import Config
from .core import APPLICATION_ID
from .instance import AiidaLabInstance
from .profile import Profile
from .util import get_docker_client
from .version import __version__


def _application_config_path():
    return Path(click.get_app_dir(APPLICATION_ID)) / "config.toml"


def _load_config():
    try:
        return Config.load(_application_config_path())
    except FileNotFoundError:
        return Config()


@dataclass
class ApplicationState:

    config_path: Path = field(default_factory=_application_config_path)
    config: Config = field(default_factory=_load_config)
    docker_client: docker.DockerClient = field(default_factory=get_docker_client)

    def save_config(self):
        self.config.save(self.config_path)

    def _apply_migration_null(self):
        # Since there is no config file on disk, we can assume that if at all,
        # there is only the default profile present.
        assert len(self.config.profiles) == 1
        assert self.config.profiles[0].name == "default"

        default_profile = self.config.profiles[0]
        instance = AiidaLabInstance(client=self.docker_client, profile=default_profile)

        # Default home bind mount path up until version 2022.1011.
        home_bind_mount_path = Path.home() / "aiidalab"

        if instance.container:
            # There is already a container present, use previously used profile.
            self.config.profiles[0] = Profile.from_container(instance.container)

        elif home_bind_mount_path.exists():
            # Using ~/aiidalab as home directory mount point, since the
            # directory exists. The default mount point was changed to be a
            # docker volume after version 2022.1011 to address issue
            # https://github.com/aiidalab/aiidalab-launch/issues/72.
            self.config.profiles[0].home_mount = str(home_bind_mount_path)

    def apply_migrations(self):
        config_changed = False

        # No config file saved to disk.
        if not self.config_path.is_file():
            self._apply_migration_null()
            config_changed = True

        # No version string stored in config.
        if self.config.version is None:
            self.config.version = str(parse(__version__))
            config_changed = True

        # Write any changes back to disk.
        if config_changed:
            self.save_config()
