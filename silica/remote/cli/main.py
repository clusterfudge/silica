"""Main CLI entry point for silica."""

import cyclopts

from silica.remote.cli.commands import (
    agent,
    antennae,
    config,
    create,
    destroy,
    memory_proxy,
    piku,
    progress,
    status,
    sync,
    tell,
    todos,
    workspace,
    workspace_environment,
)

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
app.command(memory_proxy.app)  # Memory Proxy deployment commands

# Register workspace environment commands with aliases
app.command(workspace_environment.workspace_environment)
app.command(workspace_environment.workspace_environment_)
app.command(workspace_environment.we)


def cli():
    """Entry point for CLI."""
    app()


if __name__ == "__main__":
    cli()
