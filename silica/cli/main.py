"""Main CLI entry point for silica."""

import click

from silica.cli import __version__
from silica.cli.commands import (
    create,
    config,
    status,
    todos,
    destroy,
    piku,
    sync,
    agent,
    tell,
    progress,
)


@click.group()
@click.version_option(version=__version__)
def cli():
    """A command line tool for creating workspaces for agents on top of piku."""


# Register commands
cli.add_command(create.create)
cli.add_command(config.config)
cli.add_command(status.status)
cli.add_command(todos.todos)
cli.add_command(destroy.destroy)
cli.add_command(piku.piku)
cli.add_command(sync.sync)
cli.add_command(agent.agent)
cli.add_command(tell.tell)
cli.add_command(progress.progress)

if __name__ == "__main__":
    cli()
