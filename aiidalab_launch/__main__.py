#!/usr/bin/env python
"""Convenience script wrapper to start and stop AiiDAlab via docker-compose.

Authors:
    * Carl Simon Adorf <simon.adorf@epfl.ch>
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from secrets import token_hex
from textwrap import indent

import click
import docker
from tabulate import tabulate

from .core import Config, Profile
from .util import AiidaLabInstance, get_container, get_docker_client
from .version import __version__

APPLICATION_ID = "org.aiidalab.aiidalab_launch"

APPLICATION_CONFIG_PATH = Path(click.get_app_dir(APPLICATION_ID)) / "config.toml"

MAIN_PROFILE_NAME = "main"


LOGGING_LEVELS = {
    0: logging.ERROR,
    1: logging.WARN,
    2: logging.INFO,
    3: logging.DEBUG,
}  #: a mapping of `verbose` option counts to logging levels


LOGGER = logging.getLogger(APPLICATION_ID.split(".")[-1])


def _load_config():
    try:
        return Config.load(APPLICATION_CONFIG_PATH)
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
@pass_app_state
def cli(app_state, verbose):
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

    LOGGER.info(f"Configuration file path: {APPLICATION_CONFIG_PATH}")
    LOGGER.debug(f"Configuration: \n\n{indent(app_state.config.dumps(), '    ')}")


@cli.command()
@click.pass_context
def version(ctx):
    """Show the version of aiidalab-launch."""
    click.echo(click.style(f"AiiDAlab Launch {__version__}", bold=True))


@cli.group()
def profiles():
    """Manage AiiDAlab profiles."""
    pass


@profiles.command("list")
@pass_app_state
def list_profiles(app_state):
    """List all configured AiiDAlab profiles."""
    click.echo("\n".join([profile.name for profile in app_state.config.profiles]))


@profiles.command("show")
@click.argument("profile")
@pass_app_state
def show_profile(app_state, profile):
    """Show a AiiDAlab profile configuration."""
    click.echo(app_state.config.get_profile(profile).dumps(), nl=False)


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
            app_state.config.save(APPLICATION_CONFIG_PATH)
            return
    click.echo("No changes.")


@cli.command()
@click.option(
    "--restart",
    is_flag=True,
    help="Restart the container in case that it is already running.",
)
@pass_app_state
@with_profile
def start(app_state, profile, restart):
    """Start an AiiDAlab instance on this host."""
    client = app_state.docker_client
    profile.home_mount.mkdir(exist_ok=True)

    mounts = [
        docker.types.Mount(
            target=f"/home/{profile.system_user}",
            source=str(profile.home_mount),
            type="bind",
        )
    ]

    try:
        try:
            container = client.containers.get(profile.container_name())
            if restart:
                click.echo("Restarting container...", err=True)
                container.restart()
        except docker.errors.NotFound:
            click.echo(f"Pulling image '{profile.image}'...", err=True)
            image = client.images.pull(profile.image)
            LOGGER.info(f"Pulled image: {image}")

            click.echo("Starting container...", err=True)
            container = client.containers.start(
                image=profile.image,
                name=profile.container_name(),
                environment=profile.environment(jupyter_token=token_hex(32)),
                mounts=mounts,
                ports={"8888/tcp": profile.port},
                detach=True,
                remove=True,
            )
            LOGGER.info(f"Started container: {container}")
    except docker.errors.ImageNotFound as error:
        raise click.ClickException(f"Failed to start: {error}")


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
    client = app_state.docker_client
    container = get_container(client, profile.container_name())
    click.echo("Stopping AiiDAlab... ", nl=False, err=True)
    container.stop(timeout=20)
    click.echo("stopped.", err=True)
    if remove:
        click.echo("Removing container... ", nl=False, err=True)
        container.remove()
        click.echo("done.", err=True)


@cli.command("status")
@pass_app_state
def status(app_state):
    """Show AiiDAlab instance status and entry point."""
    client = app_state.docker_client

    # Collect status of each profile
    click.echo("Collecting status info...", err=True)
    headers = ["Profile", "Container", "Status", "URL"]
    rows = []
    for instance in (
        AiidaLabInstance(client=client, profile=profile)
        for profile in app_state.config.profiles
    ):
        instance_status = instance.status()
        rows.append(
            [
                instance.profile.name,
                instance.profile.container_name(),
                {AiidaLabInstance.AiidaLabInstanceStatus.STARTING: "starting..."}.get(
                    instance_status, instance_status.name.lower()
                ),
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
    client = ctx.find_object(ApplicationState).docker_client
    container = get_container(client, profile.container_name())

    LOGGER.info(f"Executing: {' '.join(cmd)}")
    exec_id = client.api.exec_create(
        container.id,
        " ".join(cmd),
        user=None if privileged else profile.system_user,
        workdir=None if privileged else f"/home/{profile.system_user}",
    )["Id"]

    output = client.api.exec_start(exec_id, stream=True)
    for chunk in output:
        click.echo(chunk.decode(), nl=False)

    result = client.api.exec_inspect(exec_id)
    if result["ExitCode"] != 0:
        if forward_exit_code:
            ctx.exit(result["ExitCode"])
        else:
            ctx.fail(f"Command failed with exit code: {result['ExitCode']}")


if __name__ == "__main__":
    cli()
