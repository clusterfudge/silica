"""Progress command for silica."""

import time
import click
from rich.console import Console
from rich.markdown import Markdown

from silica.config import find_git_root
from silica.utils import piku as piku_utils
from silica.cli.commands.tell import tell

console = Console()


@click.command()
@click.option(
    "-w",
    "--workspace",
    help="Name for the workspace (default: agent)",
    default="agent",
)
@click.option(
    "-t",
    "--timeout",
    help="Timeout in seconds to wait for the status file to be created",
    default=10,
    type=int,
)
def progress(workspace, timeout):
    """Get a summary of the current conversation state from the agent.

    This command instructs the agent to summarize the current conversation state to a file,
    then displays the contents of that file locally.
    """
    try:
        # Get git root for app name
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return

        piku_utils.get_app_name(git_root)
        # Use a file in the agent's code directory
        status_file = "code/.silica-status"

        # First check if the status file already exists and clean it up if it does
        console.print("[yellow]Checking for existing status file...[/yellow]")
        check_cmd = (
            f"run -- \"test -f {status_file} && echo 'exists' || echo 'not_found'\""
        )
        result = piku_utils.run_piku_in_silica(
            check_cmd, workspace_name=workspace, capture_output=True, check=False
        )

        if "exists" in result.stdout:
            console.print("[yellow]Found existing status file, cleaning up...[/yellow]")
            cleanup_cmd = f"run -- rm -f {status_file}"
            piku_utils.run_piku_in_silica(
                cleanup_cmd, workspace_name=workspace, capture_output=True
            )

        # Command to instruct the agent to summarize the conversation
        # Note: The agent's working directory is already code/, so we just need the filename
        # Explicitly ask for markdown format since the file doesn't have a .md extension
        # Make sure to use properly spaced text
        summarize_cmd = tuple(
            "summarize the current conversation state to .silica-status in markdown format. Do not reference previous summarization requests.".split()
        )

        # Use the tell command to send the instruction
        console.print(
            f"[green]Asking agent to summarize conversation to: [bold]{status_file}[/bold][/green]"
        )

        # Execute the tell command to instruct the agent
        ctx = click.Context(tell)
        # Convert the tuple to a list of individual strings
        ctx.params["message"] = summarize_cmd
        ctx.params["workspace"] = workspace
        tell.invoke(ctx)

        # Wait for the file to be created with a timeout and countdown

        # Function to check if file exists
        def check_file_exists():
            check_cmd = (
                f"run -- \"test -f {status_file} && echo 'exists' || echo 'not_found'\""
            )
            result = piku_utils.run_piku_in_silica(
                check_cmd,
                workspace_name=workspace,
                capture_output=True,
                check=False,  # Don't raise exception if file doesn't exist yet
            )
            return "exists" in result.stdout

        # Continue checking until file exists or user cancels
        file_exists = False
        keep_waiting = True

        while keep_waiting and not file_exists:
            # Display countdown
            for seconds_left in range(timeout, 0, -1):
                console.print(
                    f"[yellow]Waiting for status file... {seconds_left}s remaining[/yellow]",
                    end="\r",
                )

                # Check if file exists
                if check_file_exists():
                    file_exists = True
                    console.print("\n[green]Status file found![/green]")
                    break

                time.sleep(1)

            # If file still doesn't exist after timeout, ask if user wants to continue
            if not file_exists:
                console.print(
                    "\n[yellow]Timeout reached. Status file not created yet.[/yellow]"
                )
                response = click.prompt(
                    "Would you like to continue waiting? [y/N]",
                    default="n",
                    show_default=False,
                )
                if response.lower() != "y":
                    console.print("[yellow]Cancelled by user.[/yellow]")
                    return
                else:
                    console.print("[yellow]Continuing to wait...[/yellow]")

        # Exit the loop if file was not found and user doesn't want to wait
        if not file_exists:
            return

        # Read the file content using run_piku_in_silica
        # Use -- to properly separate local and remote flags
        cat_cmd = f"run -- cat {status_file}"

        # Use run_piku_in_silica for proper environment setup
        result = piku_utils.run_piku_in_silica(
            cat_cmd, workspace_name=workspace, capture_output=True
        )

        # Display the content as markdown
        console.print("\n[bold green]Progress Summary:[/bold green]")
        console.print(Markdown(result.stdout))

        # Clean up the status file so it doesn't get accidentally committed
        cleanup_cmd = f"run -- rm -f {status_file}"
        try:
            piku_utils.run_piku_in_silica(
                cleanup_cmd, workspace_name=workspace, capture_output=True
            )
            console.print("[dim]Status file cleaned up.[/dim]")
        except Exception as cleanup_error:
            console.print(
                f"[yellow]Warning: Could not delete status file: {cleanup_error}[/yellow]"
            )

    except Exception as e:
        console.print(f"[red]Error getting progress: {e}[/red]")
