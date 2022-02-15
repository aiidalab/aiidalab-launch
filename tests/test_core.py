#!/usr/bin/env python

"""
.. currentmodule:: test_core
.. moduleauthor:: Carl Simon Adorf <simon.adorf@epfl.ch>
"""
import re
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from aiidalab_launch.core import Config, Profile, RequiresContainerInstance

VALID_PROFILE_NAMES = ["abc", "Abc", "aBC", "a0", "a-a", "a-0"]

INVALID_PROFILE_NAMES = ["", ".a", "a_a", "_a"]


def test_profile_init(profile):
    pass


@pytest.mark.parametrize("name", VALID_PROFILE_NAMES)
def test_profile_init_valid_names(profile, name):
    assert replace(profile, name=name).name == name


@pytest.mark.parametrize("name", INVALID_PROFILE_NAMES)
def test_profile_init_invalid_names(profile, name):
    with pytest.raises(ValueError):
        replace(profile, name=name)


def test_profile_equality(profile):
    assert profile == profile
    assert profile != replace(profile, name="other")


def test_profile_dumps_loads(profile):
    assert profile == Profile.loads(profile.name, profile.dumps())


def test_config_init(config):
    pass


def test_config_equality(config):
    assert config == config
    assert config != replace(config, default_profile="other")


def test_config_dumps_loads(config):
    assert config == Config.loads(config.dumps())


@pytest.mark.parametrize("safe", [True, False])
def test_config_save(tmp_path, config, safe):
    config.save(tmp_path / "config.json", safe=safe)
    assert Config.load(tmp_path / "config.json") == config


def test_config_version(config):
    assert config.version is None


async def test_instance_init(instance):
    assert await instance.status() is instance.AiidaLabInstanceStatus.DOWN


def test_instance_pull(instance):
    assert (
        "hello-world:latest"
        in replace(instance, profile=replace(instance.profile, image="hello-world"))
        .pull()
        .tags
    )
    with pytest.raises(RuntimeError):
        replace(
            instance,
            profile=replace(instance.profile, image="hello-world:no-valid-tag"),
        ).pull()


def test_instance_unknown_image(instance):
    assert (
        replace(instance, profile=replace(instance.profile, image="abc")).image is None
    )


async def test_instance_create_remove(instance):
    assert await instance.status() is instance.AiidaLabInstanceStatus.DOWN
    instance.create()
    assert instance.container is not None
    assert await instance.status() is instance.AiidaLabInstanceStatus.CREATED
    # The instance is automatically stopped and removed by the fixture
    # function.


async def test_instance_recreate(instance):
    assert await instance.status() is instance.AiidaLabInstanceStatus.DOWN
    instance.create()
    assert await instance.status() is instance.AiidaLabInstanceStatus.CREATED
    instance.recreate()
    assert instance.container is not None
    assert await instance.status() is instance.AiidaLabInstanceStatus.CREATED


async def test_instance_profile_detection(instance):
    assert await instance.status() is instance.AiidaLabInstanceStatus.DOWN
    instance.create()
    assert await instance.status() is instance.AiidaLabInstanceStatus.CREATED
    assert instance.profile == Profile.from_container(instance.container)


async def test_instance_home_bind_mount(instance):
    instance.profile.home_mount = str(Path.home() / "aiidalab")
    instance.create()
    assert await instance.status() is instance.AiidaLabInstanceStatus.CREATED
    assert instance.profile == Profile.from_container(instance.container)


async def test_profile_configuration_changes(instance):
    original_profile = deepcopy(instance.profile)

    with pytest.raises(RequiresContainerInstance):
        list(instance.configuration_changes())

    instance.create()
    assert not any(instance.configuration_changes())

    # Change name
    instance.profile.name = "some_other_name"
    assert "Profile configuration has changed." in instance.configuration_changes()
    instance.profile = deepcopy(original_profile)
    assert not any(instance.configuration_changes())

    # Change port
    assert instance.profile.port != 50000
    instance.profile.port = 50000
    assert "Profile configuration has changed." in instance.configuration_changes()
    instance.profile = deepcopy(original_profile)
    assert not any(instance.configuration_changes())

    # Change default apps
    instance.profile.default_apps = ["foo"]
    assert "Profile configuration has changed." in instance.configuration_changes()
    instance.profile = deepcopy(original_profile)
    assert not any(instance.configuration_changes())

    # Change system user
    instance.profile.system_user = "john"
    assert "Profile configuration has changed." in instance.configuration_changes()
    instance.profile = deepcopy(original_profile)
    assert not any(instance.configuration_changes())

    # Change image
    instance.profile.image = "aiidalab/aiidalab-docker-stack:1234"
    assert "Profile configuration has changed." in instance.configuration_changes()
    instance.profile = deepcopy(original_profile)
    assert not any(instance.configuration_changes())

    # Change home mount
    instance.profile.home_mount = "some_other_volume"
    assert "Profile configuration has changed." in instance.configuration_changes()
    instance.profile = deepcopy(original_profile)
    assert not any(instance.configuration_changes())


def test_instance_url_before_start(instance):
    with pytest.raises(RequiresContainerInstance):
        instance.url()


@pytest.mark.slow
@pytest.mark.trylast
@pytest.mark.usefixtures("started_instance")
class TestsAgainstStartedInstance:
    async def test_instance_status(self, started_instance):
        assert (
            await started_instance.status()
            is started_instance.AiidaLabInstanceStatus.UP
        )

    def test_instance_url(self, started_instance):
        assert re.match(
            r"http:\/\/localhost:\d+\/\?token=[a-f0-9]{64}", started_instance.url()
        )

    def test_instance_host_ports(self, started_instance):
        assert len(started_instance.host_ports()) > 0

    def test_instance_exec_create(self, docker_client, started_instance):
        exec_id = started_instance.exec_create(cmd="whoami")
        assert docker_client.api.exec_start(exec_id).decode().strip() == "aiida"

        exec_id_privileged = started_instance.exec_create(cmd="whoami", privileged=True)
        assert (
            docker_client.api.exec_start(exec_id_privileged).decode().strip() == "root"
        )
