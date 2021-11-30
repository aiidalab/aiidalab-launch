#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
.. currentmodule:: test_core
.. moduleauthor:: Carl Simon Adorf <simon.adorf@epfl.ch>
"""

from dataclasses import replace

import pytest

from aiidalab_launch.core import Config, Profile


@pytest.fixture
def profile():
    return Profile()


@pytest.fixture
def config():
    return Config()


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
