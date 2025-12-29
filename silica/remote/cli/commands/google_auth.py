"""Google authentication token export/import commands.

These commands enable transferring Google OAuth tokens between machines,
designed to work with Unix pipes over SSH:

    # Export locally, import on remote via SSH
    silica google-auth export | ssh user@remote "silica google-auth import"

    # Or save to file first
    silica google-auth export > tokens.json
    ssh user@remote "silica google-auth import" < tokens.json
"""

import json
import sys
from pathlib import Path
from typing import Annotated

import cyclopts
from rich.console import Console

console = Console(
    stderr=True
)  # Use stderr for messages so stdout stays clean for piping

app = cyclopts.App(
    name="google-auth", help="Manage Google OAuth tokens for Gmail and Calendar"
)


def get_credentials_dir() -> Path:
    """Get the credentials directory."""
    import os

    env_dir = os.environ.get("SILICA_GOOGLE_CREDENTIALS_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".hdev" / "credentials"


def get_token_files() -> dict[str, Path]:
    """Get paths to all Google token files."""
    creds_dir = get_credentials_dir()
    return {
        "gmail": creds_dir / "gmail_token.pickle",
        "calendar": creds_dir / "calendar_token.pickle",
    }


@app.command()
def export(
    gmail: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--gmail", "-g"],
            help="Export Gmail token",
        ),
    ] = False,
    calendar: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--calendar", "-c"],
            help="Export Calendar token",
        ),
    ] = False,
    output: Annotated[
        str,
        cyclopts.Parameter(
            name=["--output", "-o"],
            help="Output file (default: stdout for piping)",
        ),
    ] = "",
):
    """Export Google OAuth tokens as JSON.

    Outputs JSON to stdout by default for easy piping over SSH:

        silica remote google-auth export | ssh user@host "silica remote google-auth import"

    Or save to a file:

        silica remote google-auth export -o tokens.json
    """
    import base64

    # Default to all tokens if none specified
    if not gmail and not calendar:
        gmail = True
        calendar = True

    token_files = get_token_files()
    tokens = {}

    if gmail:
        gmail_path = token_files["gmail"]
        if gmail_path.exists():
            with open(gmail_path, "rb") as f:
                tokens["gmail_token.pickle"] = base64.b64encode(f.read()).decode(
                    "utf-8"
                )
            console.print("[green]✓[/green] Exported Gmail token", highlight=False)
        else:
            console.print(
                f"[yellow]![/yellow] Gmail token not found at {gmail_path}",
                highlight=False,
            )

    if calendar:
        calendar_path = token_files["calendar"]
        if calendar_path.exists():
            with open(calendar_path, "rb") as f:
                tokens["calendar_token.pickle"] = base64.b64encode(f.read()).decode(
                    "utf-8"
                )
            console.print("[green]✓[/green] Exported Calendar token", highlight=False)
        else:
            console.print(
                f"[yellow]![/yellow] Calendar token not found at {calendar_path}",
                highlight=False,
            )

    if not tokens:
        console.print("[red]✗[/red] No tokens found to export", highlight=False)
        sys.exit(1)

    # Output JSON
    json_output = json.dumps(tokens, indent=2)

    if output:
        with open(output, "w") as f:
            f.write(json_output)
        console.print(f"[green]✓[/green] Tokens written to {output}", highlight=False)
    else:
        # Write to stdout for piping
        print(json_output)
        console.print(
            f"[dim]Exported {len(tokens)} token(s) to stdout[/dim]", highlight=False
        )


@app.command(name="import")
def import_tokens(
    input_file: Annotated[
        str,
        cyclopts.Parameter(
            name=["--input", "-i"],
            help="Input file (default: stdin for piping)",
        ),
    ] = "",
):
    """Import Google OAuth tokens from JSON.

    Reads JSON from stdin by default for easy piping over SSH:

        silica remote google-auth export | ssh user@host "silica remote google-auth import"

    Or read from a file:

        silica remote google-auth import -i tokens.json
    """
    import base64

    # Read JSON input
    if input_file:
        with open(input_file, "r") as f:
            json_input = f.read()
        console.print(f"[dim]Reading from {input_file}[/dim]", highlight=False)
    else:
        # Read from stdin
        if sys.stdin.isatty():
            console.print(
                "[yellow]Reading from stdin (paste JSON and press Ctrl+D)...[/yellow]",
                highlight=False,
            )
        json_input = sys.stdin.read()

    try:
        tokens = json.loads(json_input)
    except json.JSONDecodeError as e:
        console.print(f"[red]✗[/red] Invalid JSON: {e}", highlight=False)
        sys.exit(1)

    if not tokens:
        console.print("[red]✗[/red] No tokens in input", highlight=False)
        sys.exit(1)

    # Ensure credentials directory exists
    creds_dir = get_credentials_dir()
    creds_dir.mkdir(parents=True, exist_ok=True)

    # Import each token
    imported = 0
    for token_name, encoded_token in tokens.items():
        token_path = creds_dir / token_name
        try:
            with open(token_path, "wb") as f:
                f.write(base64.b64decode(encoded_token))
            console.print(
                f"[green]✓[/green] Imported {token_name} to {token_path}",
                highlight=False,
            )
            imported += 1
        except Exception as e:
            console.print(
                f"[red]✗[/red] Failed to import {token_name}: {e}", highlight=False
            )

    if imported > 0:
        console.print(
            f"[green]✓[/green] Successfully imported {imported} token(s)",
            highlight=False,
        )
    else:
        console.print("[red]✗[/red] No tokens imported", highlight=False)
        sys.exit(1)


@app.command()
def status():
    """Show status of Google OAuth tokens."""
    import pickle
    from datetime import datetime

    token_files = get_token_files()

    console.print("\n[bold]Google OAuth Token Status[/bold]\n")

    for name, path in token_files.items():
        if path.exists():
            try:
                with open(path, "rb") as f:
                    creds = pickle.load(f)

                status_icon = (
                    "[green]✓[/green]" if creds.valid else "[yellow]![/yellow]"
                )
                expired_str = ""
                if hasattr(creds, "expiry") and creds.expiry:
                    if creds.expired:
                        expired_str = " [red](expired)[/red]"
                    else:
                        remaining = creds.expiry - datetime.utcnow()
                        expired_str = f" [dim](expires in {remaining})[/dim]"

                refresh_str = (
                    "[green]yes[/green]" if creds.refresh_token else "[red]no[/red]"
                )

                console.print(f"  {status_icon} [cyan]{name}[/cyan]{expired_str}")
                console.print(f"      Path: {path}")
                console.print(f"      Refresh token: {refresh_str}")
                console.print()
            except Exception as e:
                console.print(
                    f"  [red]✗[/red] [cyan]{name}[/cyan]: Error reading - {e}"
                )
                console.print(f"      Path: {path}")
                console.print()
        else:
            console.print(f"  [dim]○[/dim] [cyan]{name}[/cyan]: Not found")
            console.print(f"      Path: {path}")
            console.print()


# For direct registration in main.py
google_auth = app
