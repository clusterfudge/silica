"""Installer for heare-developer (hdev) agent."""

import subprocess
import sys
from rich.console import Console

console = Console()


def is_installed() -> bool:
    """Check if hdev is already installed."""
    try:
        # First check if it's globally available
        result = subprocess.run(
            ["hdev", "--version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        # Check if it's available via uv run
        result = subprocess.run(
            ["uv", "run", "hdev", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def install() -> bool:
    """Install hdev using pip (global) or uv (project-specific).

    Returns:
        True if installation successful, False otherwise
    """
    if is_installed():
        console.print("[green]✓ hdev is already installed[/green]")
        return True

    console.print("[yellow]Installing hdev (heare-developer)...[/yellow]")

    # Try pip first (global installation)
    try:
        console.print("[blue]Attempting global installation with pip...[/blue]")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "heare-developer"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes timeout
        )

        if result.returncode == 0:
            console.print("[green]✓ Successfully installed hdev globally[/green]")
            return True
        else:
            console.print(
                f"[yellow]Global pip installation failed: {result.stderr}[/yellow]"
            )
    except subprocess.TimeoutExpired:
        console.print("[yellow]Global pip installation timed out[/yellow]")
    except Exception as e:
        console.print(f"[yellow]Global pip installation error: {e}[/yellow]")

    # Try uv as fallback
    try:
        console.print("[blue]Attempting project installation with uv...[/blue]")
        result = subprocess.run(
            ["uv", "add", "heare-developer"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes timeout
        )

        if result.returncode == 0:
            console.print("[green]✓ Successfully installed hdev with uv[/green]")
            return True
        else:
            console.print(
                f"[red]✗ Failed to install hdev with uv: {result.stderr}[/red]"
            )
            return False

    except subprocess.TimeoutExpired:
        console.print("[red]✗ uv installation timed out[/red]")
        return False
    except Exception as e:
        console.print(f"[red]✗ uv installation failed: {e}[/red]")
        return False


def get_install_command() -> str:
    """Get the command that would be used to install this agent."""
    return "pip install heare-developer  # or: uv add heare-developer"


if __name__ == "__main__":
    # Allow running as standalone script
    success = install()
    sys.exit(0 if success else 1)
