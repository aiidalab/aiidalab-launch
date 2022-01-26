#!/usr/bin/env python

"""
.. currentmodule:: test_cli
.. moduleauthor:: Carl Simon Adorf <simon.adorf@epfl.ch>

This is the test module for the project's command-line interface (CLI)
module.
"""
from click.testing import CliRunner, Result

import aiidalab_launch.__main__ as cli
from aiidalab_launch import __version__
from aiidalab_launch.core import Profile

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


def test_list_profiles():
    runner: CliRunner = CliRunner()
    result: Result = runner.invoke(cli.cli, ["profiles", "list"])
    assert "default" in result.output.strip()


def test_show_profile():
    runner: CliRunner = CliRunner()
    result: Result = runner.invoke(cli.cli, ["profiles", "show", "default"])
    assert Profile.loads("default", result.output) == Profile()


def test_add_remove_profile():
    runner: CliRunner = CliRunner()
    result: Result = runner.invoke(
        cli.cli, ["profiles", "add", "new-profile"], input="n\n"
    )
    assert result.exit_code == 0
    assert "Added profile 'new-profile'." in result.output
    result: Result = runner.invoke(cli.cli, ["profiles", "list"])
    assert "new-profile" in result.output
    result: Result = runner.invoke(cli.cli, ["profiles", "show", "new-profile"])
    assert result.exit_code == 0
    result: Result = runner.invoke(
        cli.cli, ["profiles", "remove", "new-profile"], input="y\n"
    )
    assert result.exit_code == 0
    result: Result = runner.invoke(cli.cli, ["profiles", "list"])
    assert "new-profile" not in result.output
