from dataclasses import replace

import pytest

from aiidalab_launch.config import Config

CONFIGS = {
    "2022.1012": """
        default_profile = "default"
        version = "2022.1012"

        [profiles.default]
        port = 8888
        default_apps = [ "aiidalab-widgets-base",]
        system_user = "aiida"
        image = "aiidalab/full-stack:edge"
        home_mount = "aiidalab_default_home"
        """
}


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


@pytest.mark.parametrize("config_version", list(CONFIGS))
def test_config_loads_valid_configs(config_version):
    Config.loads(CONFIGS[config_version])
