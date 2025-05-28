"""Installer for aider agent."""

import subprocess
import sys
from rich.console import Console

console = Console()


def is_installed() -> bool:
    """Check if aider is already installed."""
    try:
        result = subprocess.run(
            ["aider", "--version"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def install() -> bool:
    """Install aider using pip.

    Returns:
        True if installation successful, False otherwise
    """
    if is_installed():
        console.print("[green]✓ aider is already installed[/green]")
        return True

    console.print("[yellow]Installing aider...[/yellow]")

    try:
        # Install aider-chat via pip (system-wide or virtual env)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "aider-chat"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes timeout
        )

        if result.returncode == 0:
            console.print("[green]✓ Successfully installed aider[/green]")
            return True
        else:
            console.print(f"[red]✗ Failed to install aider: {result.stderr}[/red]")
            return False

    except subprocess.TimeoutExpired:
        console.print("[red]✗ Installation timed out[/red]")
        return False
    except Exception as e:
        console.print(f"[red]✗ Installation failed: {e}[/red]")
        return False


def get_install_command() -> str:
    """Get the command that would be used to install this agent."""
    return "pip install aider-chat"


if __name__ == "__main__":
    # Allow running as standalone script
    success = install()
    sys.exit(0 if success else 1)
