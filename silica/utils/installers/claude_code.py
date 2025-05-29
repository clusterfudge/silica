"""Installer for claude-code agent."""

import subprocess
import sys
from rich.console import Console

console = Console()


def is_installed() -> bool:
    """Check if claude-code is already installed."""
    try:
        result = subprocess.run(
            ["claude-code", "--version"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def install() -> bool:
    """Install claude-code.

    Note: This is a placeholder implementation as claude-code may not have
    a standard installation method. Update this based on actual requirements.

    Returns:
        True if installation successful, False otherwise
    """
    if is_installed():
        console.print("[green]✓ claude-code is already installed[/green]")
        return True

    console.print("[yellow]Installing claude-code...[/yellow]")
    console.print("[red]✗ claude-code installation not yet implemented[/red]")
    console.print(
        "[blue]Please install claude-code manually and ensure it's in your PATH[/blue]"
    )

    # TODO: Implement actual claude-code installation
    # This might involve:
    # - Downloading from GitHub releases
    # - Installing via npm if it's a Node.js package
    # - Installing via a package manager

    return False


def get_install_command() -> str:
    """Get the command that would be used to install this agent."""
    return "# Manual installation required - see documentation"


if __name__ == "__main__":
    # Allow running as standalone script
    success = install()
    sys.exit(0 if success else 1)
