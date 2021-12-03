#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
.. currentmodule:: test_core
.. moduleauthor:: Carl Simon Adorf <simon.adorf@epfl.ch>
"""
from dataclasses import replace
from time import sleep

import docker
import pytest

from aiidalab_launch.core import AiidaLabInstance, Config, Profile


@pytest.fixture
def profile():
    return Profile()


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def instance(docker_client, profile):
    instance = AiidaLabInstance(client=docker_client, profile=profile)
    yield instance
    try:
        instance.stop()
        instance.remove()
    except (RuntimeError, docker.errors.NotFound):
        pass


def test_profile_init(profile):
    pass


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


def test_instance_init(instance):
    assert instance.status() is instance.AiidaLabInstanceStatus.DOWN


def test_instance_start_stop(instance):
    instance.start()
    sleep(0.1)
    assert instance.status() is instance.AiidaLabInstanceStatus.STARTING
    instance.wait_for_services(timeout=300)
    assert instance.status() is instance.AiidaLabInstanceStatus.UP
    instance.stop()
    assert instance.status() is instance.AiidaLabInstanceStatus.DOWN
