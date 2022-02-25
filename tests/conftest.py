#!/usr/bin/env python

"""
.. currentmodule:: conftest
.. moduleauthor:: Carl Simon Adorf <simon.adorf@epfl.ch>

Provide fixtures for all tests.
"""
import asyncio
import random
import re
import string
import sys
import uuid
from functools import partial
from pathlib import Path
from typing import Iterator

import click
import docker
import pytest
import requests
from requests_mock import ANY

import aiidalab_launch
from aiidalab_launch.application_state import ApplicationState
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


@pytest.fixture(scope="session", autouse=True)
def _pull_docker_image(docker_client):
    try:
        docker_client.images.pull(aiidalab_launch.profile._DEFAULT_IMAGE)
    except docker.errors.APIError:
        pytest.skip("unable to pull docker image")


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
def application_state(docker_client):
    return ApplicationState(docker_client=docker_client)


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


@pytest.fixture(autouse=True)
def _enable_docker_requests(requests_mock):
    docker_uris = re.compile(r"http\+docker:\/\/")
    requests_mock.register_uri(ANY, docker_uris, real_http=True)


# Do not request package information from PyPI
@pytest.fixture(autouse=True)
def mock_pypi_request(monkeypatch, requests_mock):
    monkeypatch.setattr(aiidalab_launch.util, "SESSION", requests.Session())
    requests_mock.register_uri(
        "GET",
        "https://pypi.python.org/pypi/aiidalab-launch/json",
        json={"releases": {"2022.1010": [{"yanked": False}]}},
    )


@pytest.fixture
def mock_pypi_request_timeout(requests_mock):
    requests_mock.register_uri(
        "GET",
        "https://pypi.python.org/pypi/aiidalab-launch/json",
        exc=requests.exceptions.Timeout,
    )


@pytest.fixture(scope="session")
def invalid_image_id(docker_client):
    for _ in range(10):  # make 10 attempts
        image_id = uuid.uuid4().hex
        try:
            docker_client.images.get(image_id)
        except docker.errors.ImageNotFound:
            yield image_id
            break
    else:
        pytest.xfail("Unable to generate invalid Docker image id.")


@pytest.fixture(autouse=True)
def _disable_docker_pull(monkeypatch):
    def no_pull(self, *args, **kwargs):
        pytest.skip("Test tried to pull docker image.")

    monkeypatch.setattr(docker.api.image.ImageApiMixin, "pull", no_pull)
    return monkeypatch


@pytest.fixture()
def enable_docker_pull(_disable_docker_pull):
    _disable_docker_pull.undo()


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
