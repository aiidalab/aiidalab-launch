from time import time

from packaging.version import parse

from aiidalab_launch.util import get_latest_version


def test_get_latest_version(mock_pypi_request):
    assert get_latest_version() == parse("2022.1010")


def test_get_latest_version_timeout(mock_pypi_request_timeout):
    start = time()
    assert get_latest_version() is None
    assert (time() - start) < 0.5
