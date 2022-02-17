from pathlib import Path


def test_init(app_config_dir, application_state):
    assert application_state.config_path.relative_to(app_config_dir)
    assert not any(app_config_dir.iterdir())


def test_save_config(application_state):
    assert not application_state.config_path.is_file()
    application_state.save_config()
    assert application_state.config_path.is_file()


def test_apply_migrations_from_empty(application_state):
    assert not application_state.config_path.is_file()
    application_state.apply_migrations()
    assert application_state.config_path.is_file()


def test_apply_migrations_aiidalab_dir_exists(application_state):
    aiidalab_dir = Path.home().joinpath("aiidalab")
    assert not application_state.config_path.is_file()
    assert not aiidalab_dir.exists()
    aiidalab_dir.mkdir()
    assert aiidalab_dir.is_dir()
    application_state.apply_migrations()
    assert application_state.config_path.is_file()
    config = application_state.config
    assert aiidalab_dir.samefile(
        Path(config.get_profile(config.default_profile).home_mount)
    )


def test_apply_migrations_aiidalab_container_exists(application_state, instance):
    aiidalab_dir = Path.home().joinpath("aiidalab")
    assert not application_state.config_path.is_file()
    assert not aiidalab_dir.exists()
    aiidalab_dir.mkdir()
    assert aiidalab_dir.is_dir()
    container = instance.create()
    application_state.apply_migrations()
    assert application_state.config_path.is_file()
    config = application_state.config
    default_profile = config.get_profile(config.default_profile)
    assert not Path(default_profile.home_mount).is_absolute()
    assert default_profile == type(default_profile).from_container(container)
