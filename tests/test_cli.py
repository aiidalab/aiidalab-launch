#!/usr/bin/env python

"""
.. currentmodule:: test_cli
.. moduleauthor:: Carl Simon Adorf <simon.adorf@epfl.ch>

This is the test module for the project's command-line interface (CLI)
module.
"""
import logging
from dataclasses import replace

import docker
import pytest
from click.testing import CliRunner, Result

import aiidalab_launch.__main__ as cli
from aiidalab_launch import __version__
from aiidalab_launch.profile import Profile

# To learn more about testing Click applications, visit the link below.
# http://click.pocoo.org/5/testing/


def test_version_displays_library_version():
    """
    Arrange/Act: Run the `version` subcommand.
    Assert: The output matches the library version.
    """
    runner: CliRunner = CliRunner()
    result: Result = runner.invoke(cli.cli, ["version"])
    assert (
        __version__ in result.output.strip()
    ), "Version number should match library version."


def test_version_displays_expected_message():
    """
    Arrange/Act: Run the `version` subcommand.
    Assert:  The output matches the library version.
    """
    runner: CliRunner = CliRunner()
    result: Result = runner.invoke(cli.cli, ["version"])
    assert "AiiDAlab Launch" in result.output.strip()


def test_version_verbose_logging():
    runner: CliRunner = CliRunner()
    result: Result = runner.invoke(cli.cli, ["-vvv", "version"])
    assert "AiiDAlab Launch" in result.output.strip()
    assert "Verbose logging is enabled." in result.output.strip()


def test_invalid_profile_name_throws():
    """
    Arrange/Act: Run `profiles show invalid` subcommand.
    Assert:  The command throws an exception due to invalid profile name.
    """
    runner: CliRunner = CliRunner()
    with pytest.raises(ValueError):
        result: Result = runner.invoke(
            cli.cli, ["profiles", "show", "invalid"], catch_exceptions=False
        )
    result: Result = runner.invoke(
        cli.cli,
        ["profiles", "show", "invalid"],
    )
    assert isinstance(result.exception, ValueError)


def test_list_profiles():
    runner: CliRunner = CliRunner()
    result: Result = runner.invoke(cli.cli, ["profiles", "list"])
    assert "default" in result.output.strip()


def test_show_profile():
    runner: CliRunner = CliRunner()
    result: Result = runner.invoke(cli.cli, ["profiles", "show", "default"])
    assert Profile.loads("default", result.output) == Profile()


def test_change_default_profile():
    runner: CliRunner = CliRunner()
    result: Result = runner.invoke(cli.cli, ["profiles", "set-default", "default"])
    assert result.exit_code == 0
    result: Result = runner.invoke(
        cli.cli, ["profiles", "set-default", "does-not-exist"]
    )
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_add_remove_profile():
    runner: CliRunner = CliRunner()

    # Add new-profile
    result: Result = runner.invoke(
        cli.cli, ["profiles", "add", "new-profile"], input="n\n"
    )
    assert result.exit_code == 0
    assert "Added profile 'new-profile'." in result.output

    # Check that new-profile exists
    result: Result = runner.invoke(cli.cli, ["profiles", "list"])
    assert "new-profile" in result.output
    result: Result = runner.invoke(cli.cli, ["profiles", "show", "new-profile"])
    assert result.exit_code == 0

    # Try add another profile with the same name (should fail)
    result: Result = runner.invoke(
        cli.cli, ["profiles", "add", "new-profile"], input="n\n"
    )
    assert result.exit_code == 1
    assert "Profile with name 'new-profile' already exists." in result.output

    # Try make new profile default
    result: Result = runner.invoke(cli.cli, ["profiles", "set-default", "new-profile"])
    assert result.exit_code == 0
    assert "Set default profile to 'new-profile'." in result.output
    # Reset default profile
    result: Result = runner.invoke(cli.cli, ["profiles", "set-default", "default"])
    assert result.exit_code == 0
    assert "Set default profile to 'default'." in result.output

    # Remove new-profile
    result: Result = runner.invoke(
        cli.cli, ["profiles", "remove", "new-profile"], input="y\n"
    )
    assert result.exit_code == 0
    result: Result = runner.invoke(cli.cli, ["profiles", "list"])
    assert "new-profile" not in result.output

    # Remove new-profile (again – should fail)
    result: Result = runner.invoke(
        cli.cli, ["profiles", "remove", "new-profile"], input="y\n"
    )
    assert result.exit_code == 1
    assert "Profile with name 'new-profile' does not exist." in result.output


def test_add_profile_invalid_name():
    runner: CliRunner = CliRunner()
    # underscores are not allowed
    result: Result = runner.invoke(cli.cli, ["profiles", "add", "new_profile"])
    assert result.exit_code == 1
    assert "Invalid profile name 'new_profile'." in result.output


@pytest.mark.slow
@pytest.mark.trylast
@pytest.mark.usefixtures("started_instance")
class TestsAgainstStartedInstance:
    def test_status(self, started_instance):
        runner: CliRunner = CliRunner()
        result: Result = runner.invoke(cli.cli, ["status"])
        assert result.exit_code == 0
        assert started_instance.profile.name in result.output
        assert started_instance.profile.container_name() in result.output
        assert "up" in result.output
        assert started_instance.profile.home_mount in result.output
        assert started_instance.url() in result.output

    def test_exec(self, started_instance):
        runner: CliRunner = CliRunner()
        result: Result = runner.invoke(cli.cli, ["exec", "--", "whoami"])
        assert result.exit_code == 0
        assert started_instance.profile.system_user in result.output

    def test_logs(self):
        runner: CliRunner = CliRunner()
        result: Result = runner.invoke(cli.cli, ["logs"])
        assert result.exit_code == 0
        assert len(result.output.strip().splitlines()) > 100

    def test_remove_running_profile(self):
        runner: CliRunner = CliRunner()
        result: Result = runner.invoke(cli.cli, ["profiles", "remove", "default"])
        assert result.exit_code == 1
        assert "is still running" in result.output


@pytest.mark.slow
@pytest.mark.trylast
class TestInstanceLifecycle:
    def test_start_stop_reset(self, instance, docker_client, caplog):
        caplog.set_level(logging.DEBUG)

        def get_volume(volume_name):
            try:
                return docker_client.volumes.get(volume_name)
            except docker.errors.NotFound:
                return None

        def assert_status_up():
            result: Result = runner.invoke(cli.cli, ["status"])
            assert result.exit_code == 0
            assert instance.profile.container_name() in result.output
            assert "up" in result.output
            assert instance.url() in result.output

        def assert_status_down():
            result: Result = runner.invoke(cli.cli, ["status"])
            assert result.exit_code == 0
            assert instance.profile.container_name() in result.output
            assert "down" in result.output
            assert "http" not in result.output

        # Start instance (non-blocking).
        runner: CliRunner = CliRunner()
        result: Result = runner.invoke(
            cli.cli, ["start", "--no-browser", "--no-pull", "--wait=0"]
        )
        assert result.exit_code == 0

        # Start instance again (blocking, should be no-op).
        runner: CliRunner = CliRunner()
        result: Result = runner.invoke(
            cli.cli, ["start", "--no-browser", "--no-pull", "--wait=300"]
        )
        assert result.exit_code == 0

        assert_status_up()
        assert get_volume(instance.profile.home_mount)
        assert get_volume(instance.profile.conda_volume_name())

        # Start instance again – should be noop.
        result: Result = runner.invoke(
            cli.cli, ["start", "--no-browser", "--no-pull", "--wait=300"]
        )
        assert "Container was already running" in result.output.strip()
        assert result.exit_code == 0
        assert_status_up()

        # Restart instance.
        # TODO: This test is currently disabled, because it is too flaky.  For
        # a currently unknown reason, the docker client will not be able to
        # reach the container anymore to check whether the notebook server is
        # online.
        # result: Result = runner.invoke(
        #     cli.cli, ["start", "--no-browser", "--wait=120", "--restart"]
        # )
        # assert result.exit_code == 0
        # assert_status_up()

        # Stop (and remove) instance.
        result: Result = runner.invoke(cli.cli, ["stop", "--remove"])
        assert result.exit_code == 0
        assert_status_down()

        assert get_volume(instance.profile.home_mount)
        assert get_volume(instance.profile.conda_volume_name())

        # Reset instance.
        result: Result = runner.invoke(
            cli.cli, ["reset"], input=f"{instance.profile.name}\n"
        )
        assert result.exit_code == 0

        assert not get_volume(instance.profile.home_mount)
        assert not get_volume(instance.profile.conda_volume_name())


@pytest.mark.slow
@pytest.mark.trylast
class TestExtraVolumes:
    def test_extra_volumes(
        self, instance, application_state, extra_volume_name, docker_client, caplog
    ):
        caplog.set_level(logging.DEBUG)

        # Add extra volume to default profile.
        config = application_state.config
        profile = config.profiles[0]
        assert profile.name == config.default_profile
        profile.extra_mounts = {f"{extra_volume_name}:/opt/extra:rw"}
        replace(
            application_state, config=replace(config, profiles=[profile])
        ).save_config()

        # Check that extra volume is picked up.
        runner: CliRunner = CliRunner()
        result = runner.invoke(cli.cli, ["profiles", "show", profile.name])
        assert result.exit_code == 0
        assert extra_volume_name in result.output

        # Start instance
        runner: CliRunner = CliRunner()
        result: Result = runner.invoke(
            cli.cli, ["start", "--no-browser", "--no-pull", "--wait=300"]
        )
        assert extra_volume_name in result.output
        assert result.exit_code == 0

        docker_client.volumes.get(extra_volume_name)  # should not throw

        # Check that instance is up.
        result: Result = runner.invoke(cli.cli, ["status"])
        assert result.exit_code == 0
        assert instance.profile.container_name() in result.output
        assert "up" in result.output
        assert instance.url() in result.output
