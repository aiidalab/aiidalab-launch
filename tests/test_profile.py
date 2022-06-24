from dataclasses import replace
from pathlib import Path

import pytest

from aiidalab_launch.profile import Profile

VALID_PROFILE_NAMES = ["abc", "Abc", "aBC", "a0", "a-a", "a-0"]

INVALID_PROFILE_NAMES = ["", ".a", "a_a", "_a"]

VALID_HOME_MOUNTS = ["{vol}", "{path}", "{path}/home"]

INVALID_HOME_MOUNTS = ["@{vol}", "./{path}"]

VALID_EXTRA_MOUNTS = [
    "{path}:/opt/test",
    "{path}:/opt/test:ro",
    "{path}:/opt/test:rw",
    "{vol}:/opt/test:ro",
    "{vol}:/opt/test:ro",
]

INVALID_EXTRA_MOUNTS = [
    "./relative/{path}:/opt/test:ro",
    "/nonexistent/{path}:/opt/test:ro",
    "{path}:/opt/test:invalid_mode",
    "invalidchar@:/opt/test:ro",
    "{vol}:/opt/test:ro:extraarg",
    "{vol}",
    "{path}/nonexistent:/opt/test",
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


@pytest.mark.parametrize("home_mount", VALID_HOME_MOUNTS)
def test_profile_init_valid_home_mounts(profile, random_volume_name, home_mount):
    home_mount = home_mount.format(path=Path.home(), vol=random_volume_name)
    assert replace(profile, home_mount=home_mount).home_mount == home_mount


@pytest.mark.parametrize("home_mount", INVALID_HOME_MOUNTS)
def test_profile_init_invalid_home_mounts(profile, random_volume_name, home_mount):
    home_mount = home_mount.format(path=Path.home(), vol=random_volume_name)
    with pytest.raises(ValueError):
        replace(profile, home_mount=home_mount)


@pytest.mark.parametrize("extra_mount", VALID_EXTRA_MOUNTS)
def test_profile_init_valid_extra_mounts(profile, random_volume_name, extra_mount):
    extra_mounts = [extra_mount.format(path=Path.home(), vol=random_volume_name)]
    assert replace(profile, extra_mounts=extra_mounts).extra_mounts == extra_mounts


@pytest.mark.parametrize("extra_mount", INVALID_EXTRA_MOUNTS)
def test_profile_init_invalid_extra_mounts(profile, random_volume_name, extra_mount):
    extra_mounts = [extra_mount.format(path=Path.home(), vol=random_volume_name)]
    with pytest.raises(ValueError):
        replace(profile, extra_mounts=extra_mounts)


def test_profile_equality(profile):
    assert profile == profile
    assert profile != replace(profile, name="other")


def test_profile_dumps_loads(profile):
    assert profile == Profile.loads(profile.name, profile.dumps())
