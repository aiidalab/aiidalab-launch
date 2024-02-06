from time import time

import pytest
from packaging.version import parse

from aiidalab_launch.util import get_latest_version, image_is_latest


def test_get_latest_version(mock_pypi_request):
    assert get_latest_version() == parse("2022.1010")


def test_get_latest_version_timeout(mock_pypi_request_timeout):
    start = time()
    assert get_latest_version() is None
    assert (time() - start) < 0.5


@pytest.mark.usefixtures("enable_docker_pull")
@pytest.mark.usefixtures("remove_created_images")
def test_image_is_latest(docker_client):
    """Test that the latest version is identified correctly."""
    # download the alpine image for testing
    image_name = "alpine:latest"
    docker_client.images.pull(image_name)

    # check that the image is identified as latest
    assert image_is_latest(docker_client, image_name)


@pytest.mark.usefixtures("enable_docker_pull")
@pytest.mark.usefixtures("remove_created_images")
def test_image_is_not_latest(docker_client):
    """Test that the outdate version is identified correctly and will ask for pull the latest."""
    # download the alpine image for testing
    old_image_name = "alpine:2.6"
    latest_image_name = "alpine:latest"

    # pull the old image and retag it as latest to mock the outdated image
    old_image = docker_client.images.pull(old_image_name)
    old_image.tag(latest_image_name)

    # check that the image is identified as latest
    assert not image_is_latest(docker_client, latest_image_name)
