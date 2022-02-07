#!/usr/bin/env python

"""
.. currentmodule:: test_core
.. moduleauthor:: Carl Simon Adorf <simon.adorf@epfl.ch>
"""
import asyncio
import re
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from time import sleep

import pytest

from aiidalab_launch.core import (
    Config,
    NoHostPortAssigned,
    Profile,
    RequiresContainerInstance,
)

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


@pytest.mark.slow
@pytest.mark.trylast
async def test_instance_start_stop(instance):
    with pytest.raises(RequiresContainerInstance):
        instance.url()
    assert await instance.status() is instance.AiidaLabInstanceStatus.DOWN
    instance.start()
    sleep(0.1)
    assert await instance.status() is instance.AiidaLabInstanceStatus.STARTING

    # It is possible that the call below will succeed/fail non-deterministically.
    assert re.match(r"http:\/\/localhost:\d+\/\?token=[a-f0-9]{64}", instance.url())

    # second call to start should have no negative effect
    instance.start()

    await asyncio.wait_for(instance.wait_for_services(), timeout=300)
    assert await instance.status() is instance.AiidaLabInstanceStatus.UP

    assert re.match(r"http:\/\/localhost:\d+\/\?token=[a-f0-9]{64}", instance.url())

    instance.stop()
    assert await instance.status() is instance.AiidaLabInstanceStatus.EXITED

    with pytest.raises(NoHostPortAssigned):
        instance.url()

    instance.remove()
    assert await instance.status() is instance.AiidaLabInstanceStatus.DOWN
