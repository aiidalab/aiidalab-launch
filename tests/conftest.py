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
import responses

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


# Avoid interfering with volumes on the host system.
@pytest.fixture(scope="class", autouse=True)
def volume_name(_random_token):
    yield f"aiidalab-launch_tests_{_random_token}_"


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
def _mocked_responses():
    "Setup mocker for all HTTP requests."
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture(autouse=True)
def _enable_docker_requests(_mocked_responses):
    "Pass-through all docker requests."
    docker_uris = re.compile(r"http\+docker:\/\/")
    _mocked_responses.add_passthru(docker_uris)


@pytest.fixture
def _pypi_response():
    "A minimal, but valid PyPI response for this package."
    return dict(
        url="https://pypi.python.org/pypi/aiidalab-launch/json",
        json={"releases": {"2022.1010": [{"yanked": False}]}},
    )


# Do not request package information from PyPI
@pytest.fixture(autouse=True)
def mock_pypi_request(monkeypatch, _mocked_responses, _pypi_response):
    "Mock the PyPI request."
    # Need to monkeypatch to prevent caching to interfere with the test.
    monkeypatch.setattr(aiidalab_launch.util, "SESSION", requests.Session())
    # Setup the mocked response for PyPI.
    _mocked_responses.upsert(responses.GET, **_pypi_response)


@pytest.fixture
def mock_pypi_request_timeout(_mocked_responses, _pypi_response):
    "Simulate a timeout while trying to reach the PyPI server."
    # Setup the timeout response.
    timeout_response = dict(
        url=_pypi_response["url"], body=requests.exceptions.Timeout()
    )
    _mocked_responses.upsert(responses.GET, **timeout_response)
    yield
    # Restore the valid mocked response for PyPI.
    _mocked_responses.upsert(responses.GET, **_pypi_response)


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
