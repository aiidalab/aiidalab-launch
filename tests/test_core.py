#!/usr/bin/env python

"""
.. currentmodule:: test_core
.. moduleauthor:: Carl Simon Adorf <simon.adorf@epfl.ch>
"""
import asyncio
from dataclasses import replace
from time import sleep

import pytest
from packaging.version import parse as parse_version

from aiidalab_launch.core import Config, Profile
from aiidalab_launch.version import __version__

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
    assert config.version == parse_version(__version__).base_version


async def test_instance_init(instance):
    assert await instance.status() is instance.AiidaLabInstanceStatus.DOWN


@pytest.mark.trylast
async def test_instance_create_remove(instance):
    assert await instance.status() is instance.AiidaLabInstanceStatus.DOWN
    instance.create()
    assert await instance.status() is instance.AiidaLabInstanceStatus.CREATED
    # The instance is automatically stopped and removed by the fixture
    # function.


@pytest.mark.slow
@pytest.mark.trylast
async def test_instance_start_stop(instance):
    assert await instance.status() is instance.AiidaLabInstanceStatus.DOWN
    instance.start()
    sleep(0.1)
    assert await instance.status() is instance.AiidaLabInstanceStatus.STARTING

    # premature additional start should have no negative effect
    instance.start()

    await asyncio.wait_for(instance.wait_for_services(), timeout=300)
    assert await instance.status() is instance.AiidaLabInstanceStatus.UP
    instance.stop()
    assert await instance.status() is instance.AiidaLabInstanceStatus.EXITED
    instance.remove()
    assert await instance.status() is instance.AiidaLabInstanceStatus.DOWN
