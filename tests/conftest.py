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
from aiidalab_launch.core import (
    AiidaLabInstance,
    Config,
    Profile,
    RequiresContainerInstance,
)


@pytest.fixture
def random_token():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


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


# Avoid interfering with used ports on the host system.
@pytest.fixture(scope="session", autouse=True)
def default_port(monkeypatch_session):
    monkeypatch_session.setattr(aiidalab_launch.core, "DEFAULT_PORT", None)
    yield None


@pytest.fixture(autouse=True)
def app_config(tmp_path, monkeypatch):
    app_config_dir = tmp_path.joinpath("app_dirs")
    monkeypatch.setattr(
        click, "get_app_dir", lambda app_id: str(app_config_dir.joinpath(app_id))
    )
    yield app_config_dir


@pytest.fixture(autouse=True)
def container_prefix(random_token, monkeypatch):
    container_prefix = f"aiidalab-launch_tests_{random_token}_"
    monkeypatch.setattr(aiidalab_launch.core, "CONTAINER_PREFIX", container_prefix)
    yield container_prefix


@pytest.fixture(autouse=True)
def home_path(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path.joinpath("home"))


@pytest.fixture
def profile():
    return Profile()


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def docker_client():
    try:
        yield docker.from_env()
    except docker.errors.DockerException:
        pytest.skip("docker not available")


@pytest.fixture
def instance(docker_client, profile):
    instance = AiidaLabInstance(client=docker_client, profile=profile)
    yield instance
    for op in (instance.stop, partial(instance.remove, data=True)):
        try:
            op()
        except (docker.errors.NotFound, RequiresContainerInstance):
            continue
        except (RuntimeError, docker.errors.APIError) as error:
            print(
                f"WARNING: Issue while stopping/removing instance: {error}",
                file=sys.stderr,
            )


@pytest.fixture
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
