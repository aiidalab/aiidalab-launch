from dataclasses import replace

import pytest

from aiidalab_launch.config import Config


def test_config_version(config):
    assert config.version is None


def test_config_init(config):
    pass


def test_config_equality(config):
    assert config == config
    assert config != replace(config, default_profile="other")


def test_config_dumps_loads(config):
    assert config == Config.loads(config.dumps())


@pytest.mark.parametrize("safe", [True, False])
def test_config_save(tmp_path, config, safe):
    config.save(tmp_path / "config.json", safe=safe)
    assert Config.load(tmp_path / "config.json") == config
