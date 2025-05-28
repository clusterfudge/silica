"""Installer for openai-codex agent."""

import subprocess
import sys
from rich.console import Console

console = Console()


def is_installed() -> bool:
    """Check if openai-codex is already installed."""
    try:
        result = subprocess.run(
            ["openai-codex", "--version"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def install() -> bool:
    """Install openai-codex.

    Note: OpenAI Codex access is typically through API, not a standalone CLI tool.
    This is a placeholder implementation.

    Returns:
        True if installation successful, False otherwise
    """
    if is_installed():
        console.print("[green]✓ openai-codex is already installed[/green]")
        return True

    console.print("[yellow]Installing openai-codex...[/yellow]")
    console.print("[red]✗ openai-codex installation not yet implemented[/red]")
    console.print(
        "[blue]OpenAI Codex typically requires API access rather than local installation[/blue]"
    )
    console.print(
        "[blue]Please ensure you have proper OpenAI API credentials configured[/blue]"
    )

    # TODO: Implement actual openai-codex installation
    # This might involve:
    # - Installing openai Python package
    # - Setting up API credentials
    # - Installing a CLI wrapper

    return False


def get_install_command() -> str:
    """Get the command that would be used to install this agent."""
    return "# API-based service - ensure OpenAI credentials are configured"


if __name__ == "__main__":
    # Allow running as standalone script
    success = install()
    sys.exit(0 if success else 1)
