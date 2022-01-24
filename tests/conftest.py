#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
.. currentmodule:: conftest
.. moduleauthor:: Carl Simon Adorf <simon.adorf@epfl.ch>

Provide fixtures for all tests.
"""
import random
import string
import sys

import click
import docker
import pytest

import aiidalab_launch
from aiidalab_launch.core import AiidaLabInstance, Profile


@pytest.fixture
def random_token():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


@pytest.fixture(autouse=True)
def default_port(monkeypatch):
    monkeypatch.setattr(aiidalab_launch.core, "DEFAULT_PORT", None)
    yield None


@pytest.fixture(autouse=True)
def app_config(tmp_path, monkeypatch):
    app_config_dir = tmp_path.joinpath("app_dirs")
    monkeypatch.setattr(
        click, "get_app_dir", lambda app_id: str(app_config_dir.joinpath(app_id))
    )
    yield app_config_dir


@pytest.fixture(autouse=True)
def default_home_mount(tmp_path, monkeypatch):
    home_mount = str(tmp_path.joinpath("home"))
    monkeypatch.setattr(aiidalab_launch.core, "_default_home_mount", lambda: home_mount)
    yield home_mount


@pytest.fixture(autouse=True)
def container_prefix(random_token, monkeypatch):
    container_prefix = f"aiidalab-launch_tests_{random_token}_"
    monkeypatch.setattr(aiidalab_launch.core, "CONTAINER_PREFIX", container_prefix)
    yield container_prefix


@pytest.fixture
def docker_client():
    try:
        yield docker.from_env()
    except docker.errors.DockerException:
        pytest.skip("docker not available")


@pytest.fixture
def profile():
    return Profile()


@pytest.fixture
def instance(docker_client, profile):
    instance = AiidaLabInstance(client=docker_client, profile=profile)
    yield instance
    try:
        instance.stop()
        instance.remove()
    except (RuntimeError, docker.errors.NotFound):
        pass
    except docker.errors.APIError as error:
        print(f"WARNING: Issue while removing instance: {error}", file=sys.stderr)


def pytest_addoption(parser):
    parser.addoption(
        "--slow",
        action="store_true",
        dest="slow",
        default=False,
        help="Enabel long running tests.",
    )


def pytest_configure(config):
    if not config.option.slow:
        setattr(config.option, "markexpr", "not slow")  # noqa
