from dataclasses import replace
from pathlib import Path

import pytest

from aiidalab_launch.profile import Profile

tmpdir = Path.home()
tmpvol = "aiidalab-launch_tests_volume"
VALID_PROFILE_NAMES = ["abc", "Abc", "aBC", "a0", "a-a", "a-0"]

INVALID_PROFILE_NAMES = ["", ".a", "a_a", "_a"]

VALID_EXTRA_MOUNTS = [
    f"{tmpdir}:/opt/test",
    f"{tmpdir}:/opt/test:ro",
    f"{tmpdir}:/opt/test:rw",
    f"{tmpvol}:/opt/test:ro",
    f"{tmpvol}:/opt/test:ro",
]

INVALID_EXTRA_MOUNTS = [
    f"./relative/{tmpdir}:/opt/test:ro",
    f"{tmpdir}:/opt/test:invalid_mode",
    "invalidchar@:/opt/test:ro",
    f"{tmpvol}:/opt/test:ro:extraarg",
    f"{tmpvol}",
    f"{tmpdir}/nonexistent:/opt/test",
    "x:/opt/test/:ro",
]


def test_profile_init(profile):
    pass


@pytest.mark.parametrize("name", VALID_PROFILE_NAMES)
def test_profile_init_valid_names(profile, name):
    assert replace(profile, name=name).name == name


@pytest.mark.parametrize("name", INVALID_PROFILE_NAMES)
def test_profile_init_invalid_names(profile, name):
    with pytest.raises(ValueError):
        replace(profile, name=name)


@pytest.mark.parametrize("extra_mount", VALID_EXTRA_MOUNTS)
def test_profile_init_valid_extra_mounts(profile, extra_mount):
    extra_mounts = [extra_mount]
    assert replace(profile, extra_mounts=extra_mounts).extra_mounts == extra_mounts


@pytest.mark.parametrize("extra_mount", INVALID_EXTRA_MOUNTS)
def test_profile_init_invalid_extra_mounts(profile, extra_mount):
    with pytest.raises(ValueError):
        replace(profile, extra_mounts=[extra_mount])


def test_profile_equality(profile):
    assert profile == profile
    assert profile != replace(profile, name="other")


def test_profile_dumps_loads(profile):
    assert profile == Profile.loads(profile.name, profile.dumps())
