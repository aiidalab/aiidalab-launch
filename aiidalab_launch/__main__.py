#!/usr/bin/env python
"""Convenience script wrapper to start and stop AiiDAlab via docker-compose.

Authors:
    * Carl Simon Adorf <simon.adorf@epfl.ch>
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path

import click
import docker
from tabulate import tabulate

from .core import APPLICATION_ID, LOGGER, AiidaLabInstance, Config, Profile, Timeout
from .util import get_docker_client, spinner
from .version import __version__

MSG_STARTUP = """Open the following URL to access AiiDAlab:

  {url}

Home mounted: {home_mount} -> /home/{system_user}"""


LOGGING_LEVELS = {
    0: logging.ERROR,
    1: logging.WARN,
    2: logging.INFO,
    3: logging.DEBUG,
}  #: a mapping of `verbose` option counts to logging levels


def _application_config_path():
    return Path(click.get_app_dir(APPLICATION_ID)) / "config.toml"


def _load_config():
    try:
        return Config.load(_application_config_path())
    except FileNotFoundError:
        return Config()


@dataclass
class ApplicationState:

    config: Config = field(default_factory=_load_config)
    docker_client: docker.DockerClient = field(default_factory=get_docker_client)


pass_app_state = click.make_pass_decorator(ApplicationState, ensure=True)


def with_profile(cmd):
    def callback(ctx, param, value):
        app_state = ctx.ensure_object(ApplicationState)
        name = value or app_state.config.default_profile
        LOGGER.info(f"Using profile: {name}")
        return app_state.config.get_profile(name)

    return click.option(
        "-p", "--profile", help="Select profile to use.", callback=callback
    )(cmd)


@click.group()
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Provide this option to increase the output verbosity of the launcher.",
)
def cli(verbose):
    # Use the verbosity count to determine the logging level...
    if verbose > 0:
        logging.basicConfig(
            level=LOGGING_LEVELS[verbose]
            if verbose in LOGGING_LEVELS
            else logging.DEBUG
        )
        click.secho(
            f"Verbose logging is enabled. "
            f"(LEVEL={logging.getLogger().getEffectiveLevel()})",
            fg="yellow",
        )

    LOGGER.info(f"Configuration file path: {_application_config_path()}")


@cli.command()
def version():
    """Show the version of aiidalab-launch."""
    click.echo(click.style(f"AiiDAlab Launch {__version__}", bold=True))


@cli.group()
def profiles():
    """Manage AiiDAlab profiles."""
    pass


@profiles.command("list")
@pass_app_state
def list_profiles(app_state):
    """List all configured AiiDAlab profiles.

    The default profile is shown in bold.
    """
    default_profile = app_state.config.default_profile
    click.echo(
        "\n".join(
            [
                click.style(
                    profile.name + (" *" if profile.name == default_profile else ""),
                    bold=profile.name == default_profile,
                )
                for profile in app_state.config.profiles
            ]
        )
    )


@profiles.command("show")
@click.argument("profile")
@pass_app_state
def show_profile(app_state, profile):
    """Show a AiiDAlab profile configuration."""
    click.echo(app_state.config.get_profile(profile).dumps(), nl=False)


@profiles.command("add")
@click.argument("profile")
@pass_app_state
@click.pass_context
def add_profile(ctx, app_state, profile):
    """Add a new AiiDAlab profile to the configuration."""
    try:
        app_state.config.get_profile(profile)
    except ValueError:
        pass
    else:
        raise click.ClickException(f"Profile with name '{profile}' already exists.")

    new_profile = Profile(name=profile)
    app_state.config.profiles.append(new_profile)
    app_state.config.save(_application_config_path())
    click.echo(f"Added profile '{profile}'.")
    if click.confirm("Do you want to edit it now?", default=True):
        ctx.invoke(edit_profile, profile=profile)


@profiles.command("remove")
@click.argument("profile")
@pass_app_state
def remove_profile(app_state, profile):
    """Remove a AiiDAlab profile from the configuration."""
    try:
        profile = app_state.config.get_profile(profile)
    except ValueError:
        raise click.ClickException(f"Profile with name '{profile}' does not exist.")
    else:
        app_state.config.profiles.remove(profile)
        app_state.config.save(_application_config_path())
        click.echo(f"Removed profile with name '{profile.name}'.")


@profiles.command("edit")
@click.argument("profile")
@pass_app_state
def edit_profile(app_state, profile):
    """Edit a AiiDAlab profile configuration."""
    current_profile = app_state.config.get_profile(profile)
    profile_edit = click.edit(current_profile.dumps(), extension=".toml")
    if profile_edit:
        new_profile = Profile.loads(profile, profile_edit)
        if new_profile != current_profile:
            app_state.config.profiles.remove(current_profile)
            app_state.config.profiles.append(new_profile)
            app_state.config.save(_application_config_path())
            return
    click.echo("No changes.")


@profiles.command("set-default")
@click.argument("profile")
@pass_app_state
def set_default_profile(app_state, profile):
    """Set a AiiDAlab profile as default."""
    try:
        app_state.config.get_profile(profile)
    except ValueError:
        raise click.ClickException(f"A profile with name '{profile}' does not exist.")
    else:
        app_state.config.default_profile = profile
        app_state.config.save(_application_config_path())
        click.echo(f"Set default profile to '{profile}'.")


@cli.command()
@click.option(
    "--restart",
    is_flag=True,
    help="Restart the container in case that it is already running.",
)
@click.option(
    "--wait",
    default=120,
    show_default=True,
    help="Time to wait after startup until all services are up. Set to zero to not wait at all and immediately return.",
)
@click.option(
    "--pull/--no-pull",
    default=True,
    help=(
        "Specify whether to pull the configured image prior to the first start "
        "of the container."
    ),
    show_default=True,
)
@click.option(
    "--no-browser",
    is_flag=True,
    help=(
        "Do not open AiiDAlab in the browser after startup. "
        "(This is disabled by default if the wait time is set to zero.)"
    ),
)
@pass_app_state
@with_profile
def start(app_state, profile, restart, wait, pull, no_browser):
    """Start an AiiDAlab instance on this host."""

    instance = AiidaLabInstance(client=app_state.docker_client, profile=profile)
    try:
        if instance.container() is None:
            if pull:
                with spinner(
                    f"Downloading image '{instance.profile.image}' (this may take a while)..."
                ):
                    instance.pull()
            else:
                raise click.ClickException(
                    f"Unable to find container '{instance.profile.container_name()}'. "
                    "Use '--pull' to pull the image prior to start."
                )

        InstanceStatus = instance.AiidaLabInstanceStatus  # local alias for brevity

        status = instance.status()
        if status is InstanceStatus.DOWN:
            with spinner("Starting container..."):
                instance.start()
        elif status is InstanceStatus.CREATED:
            with spinner("Starting previously created container..."):
                instance.restart()
        elif status is InstanceStatus.UP and restart:
            with spinner("Restarting container..."):
                instance.restart()
        elif status is InstanceStatus.UP and not restart:
            click.echo(
                "Container was already running, use --restart to restart it.", err=True
            )
        elif status is InstanceStatus.STARTING:
            click.echo("Container is already starting up...", err=True)

    except Timeout:
        raise click.ClickException(
            f"AiiDAlab instance did not start up within the provided wait period ({wait})."
        )
    except docker.errors.APIError as error:
        LOGGER.debug(f"Error during startup: {error}")
        if instance.profile.port and "port is already allocated" in str(error):
            raise click.ClickException(
                f"Port {instance.profile.port} is already allocated, choose another port "
                f"for example, by editing the profile: aiidalab-launch profiles edit {instance.profile.name}"
            )
        raise click.ClickException("Startup failed due to an unexpected error.")
    except TimeoutError:
        raise click.ClickException(
            "AiiDAlab instance did not start up within the excepted wait period."
        )
    except Exception as error:
        raise click.ClickException(f"Unknown error occurred: {error}")
    else:
        if wait:
            with spinner("Waiting for AiiDAlab services to start..."):
                instance.wait_for_services(timeout=wait)
            url = instance.url()
            click.secho(
                MSG_STARTUP.format(
                    url=instance.url(),
                    home_mount=instance.profile.home_mount,
                    system_user=instance.profile.system_user,
                ),
                fg="green",
            )
            if not no_browser:
                if click.confirm(
                    "Do you want to open AiiDAlab in the browser now?", default=True
                ):
                    click.launch(url)
        else:
            click.secho(
                "Use 'aiidalab-launch status' to check the AiiDAlab instance "
                "status and URL to open it.",
                fg="green",
            )


@cli.command()
@click.option(
    "-r",
    "--remove",
    is_flag=True,
    help="Do not only stop the container, but also remove it.",
)
@click.option(
    "-t",
    "--timeout",
    type=click.INT,
    default=20,
    help="Wait this long for the instance to shut down.",
)
@pass_app_state
@with_profile
def stop(app_state, profile, remove, timeout):
    """Stop an AiiDAlab instance on this host."""
    instance = AiidaLabInstance(client=app_state.docker_client, profile=profile)
    status = instance.status()
    if status is instance.AiidaLabInstanceStatus.UP:
        with spinner("Stopping AiiDAlab...", final="stopped."):
            instance.stop(timeout=timeout)
    if remove:
        with spinner("Removing container..."):
            instance.remove()


@cli.command("logs")
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
@pass_app_state
@with_profile
def logs(app_state, profile, follow):
    """Show the logs of a running AiiDAlab instance."""
    instance = AiidaLabInstance(client=app_state.docker_client, profile=profile)
    try:
        for chunk in instance.logs(stream=True, follow=follow):
            click.echo(chunk, nl=False)
    except RuntimeError:
        raise click.ClickException("AiiDAlab instance was not created.")
    except KeyboardInterrupt:
        pass


@cli.command("status")
@pass_app_state
def status(app_state):
    """Show AiiDAlab instance status and entry point."""
    client = app_state.docker_client

    # Collect status for each profile
    headers = ["Profile", "Container", "Status", "Mount", "URL"]
    rows = []
    instances = (
        AiidaLabInstance(client=client, profile=profile)
        for profile in app_state.config.profiles
    )

    with spinner("Collecting status info...", delay=0.5):
        for instance in instances:
            instance_status = instance.status()
            rows.append(
                [
                    instance.profile.name,
                    instance.profile.container_name(),
                    {
                        AiidaLabInstance.AiidaLabInstanceStatus.STARTING: "starting..."
                    }.get(instance_status, instance_status.name.lower()),
                    instance.profile.home_mount,
                    (
                        instance.url()
                        if instance_status is AiidaLabInstance.AiidaLabInstanceStatus.UP
                        else ""
                    ),
                ]
            )

    click.echo(tabulate(rows, headers=headers))


@cli.command()
@click.argument("cmd", nargs=-1)
@click.option("-p", "--privileged", is_flag=True)
@click.option("--forward-exit-code", is_flag=True)
@click.pass_context
@with_profile
def exec(ctx, profile, cmd, privileged, forward_exit_code):
    """Directly execute a command on a AiiDAlab instance.

    For example, to get a list of all installed aiidalab applications, run:

        aiidalab-launch exec aiidalab list

    """
    app_state = ctx.ensure_object(ApplicationState)
    instance = AiidaLabInstance(client=app_state.docker_client, profile=profile)

    exec_id = instance.exec_create(" ".join(cmd), privileged=privileged)

    output = app_state.docker_client.api.exec_start(exec_id, stream=True)
    for chunk in output:
        click.echo(chunk.decode(), nl=False)

    result = app_state.docker_client.api.exec_inspect(exec_id)
    if result["ExitCode"] != 0:
        if forward_exit_code:
            ctx.exit(result["ExitCode"])
        else:
            ctx.fail(f"Command failed with exit code: {result['ExitCode']}")


if __name__ == "__main__":
    cli()
