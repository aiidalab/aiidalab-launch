#!/usr/bin/env python
"""Tool to launch and manage AiiDAlab instances with docker.

Authors:
    * Carl Simon Adorf <simon.adorf@epfl.ch>
"""
import asyncio
import getpass
import logging
import socket
import sys
from pathlib import Path
from textwrap import wrap

import click
import docker
from packaging.version import parse
from tabulate import tabulate

from .application_state import ApplicationState
from .core import LOGGER
from .instance import AiidaLabInstance
from .profile import DEFAULT_PORT, Profile
from .util import confirm_with_value, get_latest_version, spinner, webbrowser_available
from .version import __version__

MSG_MOUNT_POINT_CONFLICT = """Warning: There is at least one other running
instance that has the same home mount point ('{home_mount}') as the instance
you are currently trying to start. Are you sure you want to continue? This may
lead to data corruption."""


MSG_STARTUP = """Open the following URL to access AiiDAlab:

  {url}

Home mounted: {home_mount} -> /home/{system_user}"""


MSG_STARTUP_SSH = """
Unable to detect a web browser which indicates that you might be running
AiiDAlab on a remote machine. If this is the case, consider to create an SSH
tunnel to access AiiDAlab on your local computer. For this, run a command
similar to

  ssh {user}@{hostname} -NfL {port}:localhost:{port}

on your local computer, then open AiiDAlab on your local computer at

  {url}

See https://github.com/aiidalab/aiidalab-launch/blob/main/ssh-forward.md for
more detailed instructions on SSH port forwarding.

Home mounted: {home_mount} -> /home/{system_user}"""

MSG_EXTRA_VOLUME = "Extra volume mounted: {source} -> {target} {mode}"


LOGGING_LEVELS = {
    0: logging.ERROR,
    1: logging.WARN,
    2: logging.INFO,
    3: logging.DEBUG,
}  #: a mapping of `verbose` option counts to logging levels


pass_app_state = click.make_pass_decorator(ApplicationState, ensure=True)


def exception_handler(exception_type, exception, traceback):  # noqa: U100
    click.echo(f"Unexpected {exception_type.__name__}: {exception}", err=True)
    click.echo(
        "Use verbose mode `aiidalab-launch --verbose` to see full stack trace", err=True
    )


def with_profile(cmd):
    def callback(ctx, param, value):  # noqa: U100
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
    logging.basicConfig(
        level=LOGGING_LEVELS[verbose] if verbose in LOGGING_LEVELS else logging.DEBUG
    )
    if verbose > 0:
        click.secho(
            f"Verbose logging is enabled. "
            f"(LEVEL={logging.getLogger().getEffectiveLevel()})",
            fg="yellow",
            err=True,
        )

    # Hide stack trace by default.
    if verbose == 0:
        sys.excepthook = exception_handler

    LOGGER.info(f"Configuration file path: {app_state.config_path}")

    latest_version = get_latest_version(timeout=0.1)
    if latest_version and latest_version > parse(__version__):
        click.secho(
            f"A new version of aiidalab-launch is available: {latest_version} (installed: {__version__})",
            fg="yellow",
        )
        if "pipx" in __file__:
            click.secho("Run `pipx upgrade aiidalab-launch` to update.", fg="yellow")

    # Apply migrations
    app_state.apply_migrations()


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
    """Show an AiiDAlab profile configuration."""
    click.echo(app_state.config.get_profile(profile).dumps(), nl=False)


@profiles.command("add")
@click.argument("profile")
@click.option(
    "--port",
    type=click.IntRange(min=1, max=65535),
    help=(
        "Specify port on which this instance will be exposed. The default port "
        "is chosen such that it does not conflict with any currently configured "
        "profiles."
    ),
)
@click.option(
    "--home-mount",
    type=click.Path(file_okay=False),
    help="Specify the path to be mounted as home directory.",
)
@pass_app_state
@click.pass_context
def add_profile(ctx, app_state, port, home_mount, profile):
    """Add a new AiiDAlab profile to the configuration."""
    try:
        app_state.config.get_profile(profile)
    except ValueError:
        pass
    else:
        raise click.ClickException(f"Profile with name '{profile}' already exists.")

    # Determine next available port or use the one provided by the user.
    configured_ports = [prof.port for prof in app_state.config.profiles if prof.port]
    port = port or (max(configured_ports, default=-1) + 1) or DEFAULT_PORT

    try:
        new_profile = Profile(
            name=profile,
            port=port,
            home_mount=home_mount,
        )
    except ValueError as error:  # invalid profile name
        raise click.ClickException(error)

    app_state.config.profiles.append(new_profile)
    app_state.save_config()
    click.echo(f"Added profile '{profile}'.")
    if click.confirm("Do you want to edit it now?", default=True):
        ctx.invoke(edit_profile, profile=profile)


@profiles.command("remove")
@click.argument("profile")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
@click.option("-f", "--force", is_flag=True, help="Proceed, ignoring any warnings.")
@pass_app_state
def remove_profile(app_state, profile, yes, force):
    """Remove an AiiDAlab profile from the configuration."""
    try:
        profile = app_state.config.get_profile(profile)
    except ValueError:
        raise click.ClickException(f"Profile with name '{profile}' does not exist.")
    else:
        if not force:
            instance = AiidaLabInstance(client=app_state.docker_client, profile=profile)
            status = asyncio.run(instance.status())
            if status not in (
                instance.AiidaLabInstanceStatus.DOWN,
                instance.AiidaLabInstanceStatus.CREATED,
                instance.AiidaLabInstanceStatus.EXITED,
            ):
                raise click.ClickException(
                    f"The instance associated with profile '{profile.name}' "
                    "is still running. Use the -f/--force option to remove the "
                    "profile anyways."
                )

        if yes or click.confirm(
            f"Are you sure you want to remove profile '{profile.name}'?"
        ):
            app_state.config.profiles.remove(profile)
            app_state.save_config()
            click.echo(f"Removed profile with name '{profile.name}'.")


@profiles.command("edit")
@click.argument("profile")
@pass_app_state
def edit_profile(app_state, profile):
    """Edit an AiiDAlab profile configuration."""
    current_profile = app_state.config.get_profile(profile)
    profile_edit = click.edit(current_profile.dumps(), extension=".toml")
    if profile_edit:
        new_profile = Profile.loads(profile, profile_edit)
        if new_profile != current_profile:
            app_state.config.profiles.remove(current_profile)
            app_state.config.profiles.append(new_profile)
            app_state.save_config()
            return
    click.echo("No changes.")


@profiles.command("set-default")
@click.argument("profile")
@pass_app_state
def set_default_profile(app_state, profile):
    """Set an AiiDAlab profile as default."""
    try:
        app_state.config.get_profile(profile)
    except ValueError:
        raise click.ClickException(f"A profile with name '{profile}' does not exist.")
    else:
        app_state.config.default_profile = profile
        app_state.save_config()
        click.echo(f"Set default profile to '{profile}'.")


async def _find_mount_point_conflict(client, profile, other_profiles):
    """Find running instances with the same home mount point.

    To protect users from inadvertently starting a second profile with the same
    home mount point. Running two containers with the same home mount point has
    potential for data corruption.
    """
    for other_profile in other_profiles:
        if (
            other_profile != profile
            and Path(other_profile.home_mount).resolve()
            == Path(profile.home_mount).resolve()
        ):
            status = await AiidaLabInstance(
                client=client, profile=other_profile
            ).status()
            if status is not AiidaLabInstance.AiidaLabInstanceStatus.DOWN:
                yield other_profile


async def _async_start(
    app_state, profile, restart, wait, pull, no_browser, show_ssh_help, force
):
    # Check for potential mount point conflicts.
    instance = AiidaLabInstance(client=app_state.docker_client, profile=profile)

    if not force:
        conflict = False
        with spinner("Check for potential conflicts...", delay=0.1):
            async for p in _find_mount_point_conflict(
                app_state.docker_client,
                profile,
                app_state.config.profiles,
            ):
                conflict = True
                break

        if conflict:
            msg_warn = MSG_MOUNT_POINT_CONFLICT.format(home_mount=profile.home_mount)
            click.confirm(
                click.style("\n".join(wrap(msg_warn)), fg="yellow"),
                abort=True,
            )

    # Obtain image (either via pull or local).
    if pull:
        try:
            msg = (
                f"Downloading image '{instance.profile.image}', this may take a while..."
                if instance.image is None
                else f"Downloading latest version of '{instance.profile.image}'..."
            )
            with spinner(msg):
                instance.pull()
        except RuntimeError as error:
            raise click.ClickException(str(error))
    elif instance.image is None:
        raise click.ClickException(
            f"Unable to find image '{profile.image}'. "
            "Try to use '--pull' to pull the image prior to start."
        )

    # Check if the container configuration has changed.
    if instance.container:
        configuration_changed = any(instance.configuration_changes())
    else:
        configuration_changed = False

    try:

        InstanceStatus = instance.AiidaLabInstanceStatus  # local alias for brevity

        status = await instance.status()

        # Container needs to be started.
        if status in (
            InstanceStatus.DOWN,
            InstanceStatus.CREATED,
            InstanceStatus.EXITED,
        ):
            if configuration_changed:
                with spinner("Recreating container..."):
                    instance.recreate()
            with spinner("Starting container..."):
                instance.start()

        # Container is already up.
        elif status is InstanceStatus.UP and restart:
            with spinner("Restarting container..."):
                if configuration_changed:
                    instance.stop()
                    instance.recreate()
                    instance.start()
                else:
                    instance.restart()
        elif status is InstanceStatus.UP and not restart:
            if configuration_changed:
                click.secho(
                    "Container is already running, however the configuration "
                    "has changed. A restart with --restart is recommended.",
                    fg="yellow",
                )
            else:
                click.echo(
                    "Container was already running, use --restart to restart it.",
                    err=True,
                )

        # Container is already starting.
        elif status is InstanceStatus.STARTING:
            click.echo("Container is already starting up...", err=True)

        # Unknown condition.
        else:
            raise RuntimeError(
                "Container already exists, but failed to determine status."
            )

    except docker.errors.APIError as error:
        LOGGER.debug(f"Error during startup: {error}")
        if instance.profile.port and "port is already allocated" in str(error):
            raise click.ClickException(
                f"Port {instance.profile.port} is already allocated, choose another port "
                f"for example, by editing the profile: aiidalab-launch profiles edit {instance.profile.name}"
            )
        raise click.ClickException("Startup failed due to an unexpected error.")
    except asyncio.TimeoutError:
        raise click.ClickException(
            "AiiDAlab instance did not start up within the excepted wait period."
        )
    except Exception as error:
        raise click.ClickException(f"Unknown error occurred: {error}")
    else:
        if wait:
            try:
                with spinner("Waiting for AiiDAlab instance to get ready..."):
                    echo_logs = asyncio.create_task(instance.echo_logs())
                    await asyncio.wait_for(instance.wait_for_services(), timeout=wait)
                    echo_logs.cancel()
                    LOGGER.debug("AiiDAlab instance ready.")
            except asyncio.TimeoutError:
                raise click.ClickException(
                    f"AiiDAlab instance did not start up within the provided wait period ({wait})."
                )
            except RuntimeError:
                raise click.ClickException(
                    "The AiiDAlab instance failed to start. You can inspect "
                    "the container output logs with "
                    f"'aiidalab-launch logs -p {instance.profile.name}' "
                    "and increase the output verbosity with "
                    "'aiidalab-launch -vvv start'."
                )
            LOGGER.debug("Preparing startup message.")
            msg_startup = (
                MSG_STARTUP_SSH
                if (show_ssh_help or not webbrowser_available())
                else MSG_STARTUP
            )
            url = instance.url()
            host_ports = instance.host_ports()
            assert len(host_ports) > 0
            click.secho(
                msg_startup.format(
                    url=url,
                    home_mount=instance.profile.home_mount,
                    system_user=instance.profile.system_user,
                    user=getpass.getuser(),
                    port=host_ports[0],
                    hostname=socket.getfqdn(),
                ).lstrip(),
                fg="green",
            )

            for extra_mount in profile.extra_mounts:
                source, target, mode = profile.parse_extra_mount(extra_mount)
                click.secho(
                    MSG_EXTRA_VOLUME.format(
                        source=source,
                        target=target,
                        mode=f"({mode})" if mode else "",
                    ).lstrip(),
                    fg="green",
                )

            if not no_browser and webbrowser_available():
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
@click.option(
    "--show-ssh-port-forwarding-help",
    "show_ssh_help",
    is_flag=True,
    help="Show guidance on SSH port forwarding.",
)
@click.option(
    "-f", "--force", is_flag=True, help="Ignore any warnings and start anyways."
)
@pass_app_state
@with_profile
def start(*args, **kwargs):
    """Start an AiiDAlab instance on this host."""
    asyncio.run(_async_start(*args, **kwargs))


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
    status = asyncio.run(instance.status())
    if status not in (
        instance.AiidaLabInstanceStatus.DOWN,
        instance.AiidaLabInstanceStatus.CREATED,
        instance.AiidaLabInstanceStatus.EXITED,
    ):
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
    instances = [
        AiidaLabInstance(client=client, profile=profile)
        for profile in app_state.config.profiles
    ]

    async def fetch_status(instances):
        results = await asyncio.gather(*(instance.status() for instance in instances))
        return list(zip(instances, results))

    with spinner("Collecting status info...", delay=0.5):
        for instance, instance_status in asyncio.run(fetch_status(instances)):
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
@click.option("--privileged", is_flag=True)
@click.option("--forward-exit-code", is_flag=True)
@click.option(
    "--wait/--no-wait",
    help="Wait on AiiDAlab services to get ready before sending the command.",
    show_default=True,
    default=True,
)
@click.pass_context
@with_profile
def exec(ctx, profile, cmd, privileged, forward_exit_code, wait):
    """Directly execute a command on an AiiDAlab instance.

    For example, to get a list of all installed aiidalab applications, run:

        aiidalab-launch exec -- aiidalab list

    """
    app_state = ctx.ensure_object(ApplicationState)
    instance = AiidaLabInstance(client=app_state.docker_client, profile=profile)
    try:
        if wait:
            with spinner("Waiting for AiiDAlab to get ready...", delay=0.5):
                asyncio.run(asyncio.wait_for(instance.wait_for_services(), timeout=60))
        with spinner("Send command to container...", delay=1.0):
            exec_id = instance.exec_create(" ".join(cmd), privileged=privileged)
    except (RuntimeError, asyncio.TimeoutError):
        raise click.ClickException("AiiDAlab instance is not available. Is it running?")

    output = app_state.docker_client.api.exec_start(exec_id, stream=True)
    for chunk in output:
        click.echo(chunk.decode(), nl=False)

    result = app_state.docker_client.api.exec_inspect(exec_id)
    if result["ExitCode"] != 0:
        if forward_exit_code:
            ctx.exit(result["ExitCode"])
        else:
            ctx.fail(f"Command failed with exit code: {result['ExitCode']}")


@cli.command()
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
@with_profile
@pass_app_state
def reset(app_state, profile, yes):
    """Reset an AiiDAlab instance.

    This function removes all user-installed apps and generated data. Use with
    caution.
    """
    # Check (and abort) in case that the instance is running.
    instance = AiidaLabInstance(client=app_state.docker_client, profile=profile)
    status = asyncio.run(instance.status())
    if status not in (
        instance.AiidaLabInstanceStatus.DOWN,
        instance.AiidaLabInstanceStatus.CREATED,
        instance.AiidaLabInstanceStatus.EXITED,
    ):
        raise click.ClickException(
            f"The instance associated with profile '{profile.name}' "
            "is still running. Please stop it prior to reset."
        )

    click.secho(
        f"Resetting instance for profile '{profile.name}'. This action cannot be undone!",
        err=True,
        fg="red",
    )

    if not yes:
        confirm_with_value(
            profile.name, "Please enter the name of the profile to continue", abort=True
        )

    click.echo("Removing container and associated (data) volumes.")
    instance.remove(conda=True, data=True)


if __name__ == "__main__":
    cli()
