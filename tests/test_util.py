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
def test_image_is_latest(docker_client):
    """Test that the latest version is identified correctly."""
    # download the alpine image for testing
    image_name = "alpine:latest"
    docker_client.images.pull(image_name)

    # check that the image is identified as latest
    assert image_is_latest(docker_client, image_name)
