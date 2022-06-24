from dataclasses import replace
from pathlib import Path

import pytest

from aiidalab_launch.profile import Profile

VALID_PROFILE_NAMES = ["abc", "Abc", "aBC", "a0", "a-a", "a-0"]

INVALID_PROFILE_NAMES = ["", ".a", "a_a", "_a"]

VALID_EXTRA_MOUNTS = [
    "{dir}:/opt/test",
    "{dir}:/opt/test:ro",
    "{dir}:/opt/test:rw",
    "{vol}:/opt/test:ro",
    "{vol}:/opt/test:ro",
]

INVALID_EXTRA_MOUNTS = [
    "./relative/{dir}:/opt/test:ro",
    "/nonexistent/{dir}:/opt/test:ro",
    "{dir}:/opt/test:invalid_mode",
    "invalidchar@:/opt/test:ro",
    "{vol}:/opt/test:ro:extraarg",
    "{vol}",
    "{dir}/nonexistent:/opt/test",
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
def test_profile_init_valid_extra_mounts(profile, volume_name, extra_mount):
    extra_mounts = [extra_mount.format(dir=Path.home(), vol=volume_name)]
    assert replace(profile, extra_mounts=extra_mounts).extra_mounts == extra_mounts


@pytest.mark.parametrize("extra_mount", INVALID_EXTRA_MOUNTS)
def test_profile_init_invalid_extra_mounts(profile, volume_name, extra_mount):
    extra_mounts = [extra_mount.format(dir=Path.home(), vol=volume_name)]
    with pytest.raises(ValueError):
        replace(profile, extra_mounts=extra_mounts)


def test_profile_equality(profile):
    assert profile == profile
    assert profile != replace(profile, name="other")


def test_profile_dumps_loads(profile):
    assert profile == Profile.loads(profile.name, profile.dumps())
