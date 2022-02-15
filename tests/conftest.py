#!/usr/bin/env python

"""
.. currentmodule:: conftest
.. moduleauthor:: Carl Simon Adorf <simon.adorf@epfl.ch>

Provide fixtures for all tests.
"""
import asyncio
import random
import string
import sys
from functools import partial
from pathlib import Path
from typing import Iterator

import click
import docker
import pytest

import aiidalab_launch
from aiidalab_launch.config import Config
from aiidalab_launch.instance import AiidaLabInstance, RequiresContainerInstance
from aiidalab_launch.profile import Profile


# Redefine event_loop fixture to be session-scoped.
# See: https://github.com/pytest-dev/pytest-asyncio#async-fixtures
@pytest.fixture(scope="session")
def event_loop(request: "pytest.FixtureRequest") -> Iterator[asyncio.AbstractEventLoop]:
    """Create an instance of the default event loop for the whole session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Adapted from https://github.com/pytest-dev/pytest/issues/1872#issuecomment-375108891:
@pytest.fixture(scope="session")
def monkeypatch_session():
    from _pytest.monkeypatch import MonkeyPatch

    m = MonkeyPatch()
    yield m
    m.undo()


@pytest.fixture(scope="session")
def docker_client():
    try:
        yield docker.from_env()
    except docker.errors.DockerException:
        pytest.skip("docker not available")


# Avoid interfering with used ports on the host system.
@pytest.fixture(scope="session", autouse=True)
def _default_port(monkeypatch_session):
    monkeypatch_session.setattr(aiidalab_launch.profile, "DEFAULT_PORT", None)
    yield None


@pytest.fixture(scope="class")
def _random_token():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


# Avoid interfering with containers on the host system.
@pytest.fixture(scope="class", autouse=True)
def _container_prefix(_random_token, monkeypatch_session):
    container_prefix = f"aiidalab-launch_tests_{_random_token}_"
    monkeypatch_session.setattr(
        aiidalab_launch.profile, "CONTAINER_PREFIX", container_prefix
    )
    yield container_prefix


# Avoid accidentally reading or writing from the host home directory.
@pytest.fixture(scope="class", autouse=True)
def home_path(tmp_path_factory, monkeypatch_session):
    home_dir = tmp_path_factory.mktemp("home")
    assert isinstance(home_dir, Path)
    monkeypatch_session.setattr(Path, "home", lambda: home_dir)


# Avoid accidentically reading or writing from the host config directory.
@pytest.fixture(scope="class", autouse=True)
def app_config_dir(tmp_path_factory, monkeypatch_session):
    app_config_dir = tmp_path_factory.mktemp("app_dirs")
    monkeypatch_session.setattr(
        click, "get_app_dir", lambda app_id: str(app_config_dir.joinpath(app_id))
    )
    yield app_config_dir


@pytest.fixture(scope="class")
def config():
    return Config()


@pytest.fixture(scope="class")
def profile(config):
    return Profile()


@pytest.fixture(scope="class")
def instance(docker_client, profile):
    instance = AiidaLabInstance(client=docker_client, profile=profile)
    yield instance
    for op in (instance.stop, partial(instance.remove, conda=True, data=True)):
        try:
            op()
        except (docker.errors.NotFound, RequiresContainerInstance):
            continue
        except (RuntimeError, docker.errors.APIError) as error:
            print(
                f"WARNING: Issue while stopping/removing instance: {error}",
                file=sys.stderr,
            )


@pytest.fixture(scope="class")
async def started_instance(instance):
    instance.create()
    assert instance.container is not None
    assert await instance.status() is instance.AiidaLabInstanceStatus.CREATED
    instance.start()
    assert (
        await asyncio.wait_for(instance.status(), timeout=20)
        is instance.AiidaLabInstanceStatus.STARTING
    )
    await asyncio.wait_for(instance.wait_for_services(), timeout=300)
    assert (
        await asyncio.wait_for(instance.status(), timeout=20)
        is instance.AiidaLabInstanceStatus.UP
    )
    yield instance


def pytest_addoption(parser):
    parser.addoption(
        "--slow",
        action="store_true",
        dest="slow",
        default=False,
        help="Enable long running tests.",
    )


def pytest_configure(config):
    if not config.option.slow:
        setattr(config.option, "markexpr", "not slow")  # noqa
