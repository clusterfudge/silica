"""Main CLI entry point for silica."""

import cyclopts

from silica.remote.cli.commands import (
    config,
    todos,
    piku,
    sync,
    agent,
    tell,
    progress,
    workspace,
    workspace_environment,
    antennae,
)
from silica.remote.cli.commands import create, destroy, status

app = cyclopts.App(
    help="A command line tool for creating workspaces for agents on top of piku."
)


# Register simple commands
app.command(create.create)
app.command(status.status)
app.command(destroy.destroy)
app.command(sync.sync)
app.command(agent.agent)
app.command(tell.tell)
app.command(progress.progress)
app.command(antennae.antennae)

# Register group commands (sub-apps)
app.command(config.config)
app.command(todos.todos)
app.command(piku.piku)
app.command(workspace.workspace)

# Register workspace environment commands with aliases
app.command(workspace_environment.workspace_environment)
app.command(workspace_environment.workspace_environment_)
app.command(workspace_environment.we)


def cli():
    """Entry point for CLI."""
    app()


if __name__ == "__main__":
    cli()
