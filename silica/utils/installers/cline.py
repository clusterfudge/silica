"""Installer for cline agent."""

import subprocess
import sys
from rich.console import Console

console = Console()


def is_installed() -> bool:
    """Check if cline is already installed."""
    try:
        result = subprocess.run(
            ["cline", "--version"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def install() -> bool:
    """Install cline.

    Cline is typically installed via npm as it's a VS Code extension with CLI component.

    Returns:
        True if installation successful, False otherwise
    """
    if is_installed():
        console.print("[green]✓ cline is already installed[/green]")
        return True

    console.print("[yellow]Installing cline...[/yellow]")

    # Check if npm is available
    try:
        npm_result = subprocess.run(
            ["npm", "--version"], capture_output=True, text=True, timeout=5
        )
        if npm_result.returncode != 0:
            console.print(
                "[red]✗ npm not found. Please install Node.js and npm first[/red]"
            )
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        console.print(
            "[red]✗ npm not found. Please install Node.js and npm first[/red]"
        )
        return False

    try:
        # Install cline via npm (global installation)
        result = subprocess.run(
            ["npm", "install", "-g", "cline"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes timeout
        )

        if result.returncode == 0:
            console.print("[green]✓ Successfully installed cline[/green]")
            return True
        else:
            console.print(f"[red]✗ Failed to install cline: {result.stderr}[/red]")
            console.print(
                "[blue]Note: You may need to install the cline VS Code extension separately[/blue]"
            )
            return False

    except subprocess.TimeoutExpired:
        console.print("[red]✗ Installation timed out[/red]")
        return False
    except Exception as e:
        console.print(f"[red]✗ Installation failed: {e}[/red]")
        return False


def get_install_command() -> str:
    """Get the command that would be used to install this agent."""
    return "npm install -g cline"


if __name__ == "__main__":
    # Allow running as standalone script
    success = install()
    sys.exit(0 if success else 1)
