#!/usr/bin/env python3
"""Python environment check command for Silica CLI."""

import click
import os
from rich.console import Console
from pathlib import Path
import sys

# Add silica to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.python_compatibility import (
    diagnose_python_environment,
    print_python_installation_help,
    configure_uv_python,
    find_suitable_python,
)

console = Console()


@click.command()
@click.option(
    "--fix", is_flag=True, help="Attempt to automatically configure UV_PYTHON"
)
@click.option(
    "--help-install", is_flag=True, help="Show Python installation instructions"
)
def python_check(fix: bool, help_install: bool):
    """Check Python environment compatibility and provide fixes.

    This command helps diagnose Python version issues, especially on
    systems like Raspberry Pi where the system Python may be too old.
    """
    console.print("[bold blue]Silica Python Environment Check[/bold blue]")

    if help_install:
        print_python_installation_help()
        return

    # Run diagnosis
    diagnose_python_environment()

    if fix:
        console.print(
            "\n[bold blue]Attempting to fix Python configuration...[/bold blue]"
        )
        if configure_uv_python():
            console.print("[green]✓ Successfully configured UV_PYTHON[/green]")
            console.print(f"[green]Set UV_PYTHON={os.environ.get('UV_PYTHON')}[/green]")
            console.print(
                "\n[blue]To make this permanent, add to your shell config:[/blue]"
            )
            console.print(f"export UV_PYTHON={os.environ.get('UV_PYTHON')}")
        else:
            console.print("[red]✗ Could not automatically configure Python[/red]")
            console.print("\n[yellow]Manual intervention required:[/yellow]")
            print_python_installation_help()
    else:
        # Check if we can find a suitable Python
        suitable_python = find_suitable_python()
        if suitable_python:
            console.print(
                f"\n[green]✓ Found suitable Python: {suitable_python}[/green]"
            )
            console.print(
                "[blue]Run with --fix to automatically configure UV_PYTHON[/blue]"
            )
        else:
            console.print("\n[red]✗ No suitable Python found[/red]")
            console.print(
                "[blue]Run with --help-install for installation instructions[/blue]"
            )
