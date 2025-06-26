#!/usr/bin/env python3
"""Python compatibility utilities for Silica.

This module handles Python version detection and configuration,
especially for environments with older system Python versions
like Raspberry Pi.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Tuple
from rich.console import Console

console = Console()


def get_python_version(python_executable: str) -> Optional[Tuple[int, int, int]]:
    """Get the version of a Python executable.

    Args:
        python_executable: Path to Python executable

    Returns:
        Tuple of (major, minor, patch) version numbers or None if failed
    """
    try:
        result = subprocess.run(
            [python_executable, "--version"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            # Parse "Python 3.11.2" format
            version_str = result.stdout.strip()
            if version_str.startswith("Python "):
                version_parts = version_str.split()[1].split(".")
                return tuple(int(x) for x in version_parts[:3])
    except (
        subprocess.TimeoutExpired,
        subprocess.SubprocessError,
        ValueError,
        FileNotFoundError,
    ):
        pass
    return None


def find_suitable_python() -> Optional[str]:
    """Find a suitable Python interpreter (3.11+).

    Returns:
        Path to suitable Python executable or None if not found
    """
    # List of Python executables to try, in order of preference
    python_candidates = [
        # Specific versions first
        "python3.12",
        "python3.11",
        # Generic versions
        "python3",
        "python",
        # Common installation paths
        "/usr/local/bin/python3.12",
        "/usr/local/bin/python3.11",
        "/opt/python/3.12/bin/python3",
        "/opt/python/3.11/bin/python3",
        # Homebrew on macOS
        "/opt/homebrew/bin/python3.12",
        "/opt/homebrew/bin/python3.11",
        "/usr/local/homebrew/bin/python3.12",
        "/usr/local/homebrew/bin/python3.11",
        # Pyenv
        f"{Path.home()}/.pyenv/versions/3.12.0/bin/python",
        f"{Path.home()}/.pyenv/versions/3.11.0/bin/python",
    ]

    # Also check pyenv versions if available
    pyenv_path = shutil.which("pyenv")
    if pyenv_path:
        try:
            result = subprocess.run(
                ["pyenv", "versions", "--bare"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for version in result.stdout.strip().split("\n"):
                    version = version.strip()
                    if version.startswith("3.1") and int(version.split(".")[1]) >= 11:
                        pyenv_python = (
                            f"{Path.home()}/.pyenv/versions/{version}/bin/python"
                        )
                        python_candidates.insert(0, pyenv_python)
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass

    # Check each candidate
    for candidate in python_candidates:
        if not candidate:
            continue

        # Check if executable exists
        if not shutil.which(candidate) and not Path(candidate).exists():
            continue

        version = get_python_version(candidate)
        if version and version >= (3, 11, 0):
            console.print(
                f"[green]Found suitable Python: {candidate} (version {'.'.join(map(str, version))})[/green]"
            )
            return candidate

    return None


def check_uv_python_support(python_executable: str) -> bool:
    """Check if Python executable supports uv requirements (Python 3.8+, -I flag).

    Args:
        python_executable: Path to Python executable

    Returns:
        True if Python supports uv requirements
    """
    version = get_python_version(python_executable)
    if not version or version < (3, 8, 0):
        return False

    # Test the -I flag specifically
    try:
        result = subprocess.run(
            [python_executable, "-I", "-c", "import sys; print('OK')"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and "OK" in result.stdout
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False


def configure_uv_python() -> bool:
    """Configure UV to use a suitable Python interpreter.

    Returns:
        True if successfully configured, False otherwise
    """
    # Check if UV_PYTHON is already set and valid
    existing_uv_python = os.environ.get("UV_PYTHON")
    if existing_uv_python:
        if check_uv_python_support(existing_uv_python):
            console.print(
                f"[green]Using existing UV_PYTHON: {existing_uv_python}[/green]"
            )
            return True
        else:
            console.print(
                f"[yellow]Existing UV_PYTHON ({existing_uv_python}) is not suitable[/yellow]"
            )

    # Find a suitable Python
    suitable_python = find_suitable_python()
    if not suitable_python:
        console.print(
            "[red]No suitable Python interpreter found (need Python 3.11+)[/red]"
        )
        return False

    # Verify it works with uv
    if not check_uv_python_support(suitable_python):
        console.print(
            f"[red]Python {suitable_python} doesn't support uv requirements[/red]"
        )
        return False

    # Set UV_PYTHON environment variable
    os.environ["UV_PYTHON"] = suitable_python
    console.print(f"[green]Configured UV_PYTHON: {suitable_python}[/green]")

    return True


def print_python_installation_help():
    """Print helpful information about installing Python 3.11+ on various systems."""
    console.print("\n[bold red]Python 3.11+ Installation Help[/bold red]")
    console.print(
        "\nYour system needs Python 3.11 or newer. Here are installation options:\n"
    )

    console.print("[bold]Raspberry Pi OS / Debian/Ubuntu:[/bold]")
    console.print("  sudo apt update")
    console.print("  sudo apt install software-properties-common")
    console.print("  sudo add-apt-repository ppa:deadsnakes/ppa")
    console.print("  sudo apt update")
    console.print("  sudo apt install python3.11 python3.11-venv python3.11-pip")
    console.print("")

    console.print("[bold]Using pyenv (recommended):[/bold]")
    console.print("  curl https://pyenv.run | bash")
    console.print("  # Add to ~/.bashrc or ~/.zshrc:")
    console.print('  export PATH="$HOME/.pyenv/bin:$PATH"')
    console.print('  eval "$(pyenv init -)"')
    console.print("  # Restart shell, then:")
    console.print("  pyenv install 3.11.7")
    console.print("  pyenv global 3.11.7")
    console.print("")

    console.print("[bold]Building from source (advanced):[/bold]")
    console.print("  wget https://www.python.org/ftp/python/3.11.7/Python-3.11.7.tgz")
    console.print("  tar xzf Python-3.11.7.tgz")
    console.print("  cd Python-3.11.7")
    console.print("  ./configure --enable-optimizations")
    console.print("  make -j$(nproc)")
    console.print("  sudo make altinstall")
    console.print("")

    console.print("[bold]After installation:[/bold]")
    console.print("  # Verify installation:")
    console.print("  python3.11 --version")
    console.print("  # Then try running Silica again")
    console.print("")


def diagnose_python_environment():
    """Diagnose the current Python environment and provide recommendations."""
    console.print("\n[bold blue]Python Environment Diagnosis[/bold blue]")

    # Check system Python
    system_python = shutil.which("python") or "/usr/bin/python"
    system_version = get_python_version(system_python)
    if system_version:
        console.print(
            f"System Python: {system_python} (version {'.'.join(map(str, system_version))})"
        )
        if system_version < (3, 8, 0):
            console.print("[red]  ⚠ Too old for uv (need 3.8+)[/red]")
        elif system_version < (3, 11, 0):
            console.print("[yellow]  ⚠ Too old for this project (need 3.11+)[/yellow]")
        else:
            console.print("[green]  ✓ Compatible[/green]")
    else:
        console.print(
            f"System Python: {system_python} [red]not found or not working[/red]"
        )

    # Check python3
    python3 = shutil.which("python3")
    if python3:
        python3_version = get_python_version(python3)
        if python3_version:
            console.print(
                f"Python3: {python3} (version {'.'.join(map(str, python3_version))})"
            )
            if python3_version < (3, 8, 0):
                console.print("[red]  ⚠ Too old for uv (need 3.8+)[/red]")
            elif python3_version < (3, 11, 0):
                console.print(
                    "[yellow]  ⚠ Too old for this project (need 3.11+)[/yellow]"
                )
            else:
                console.print("[green]  ✓ Compatible[/green]")

    # Check for specific versions
    for version in ["3.11", "3.12"]:
        python_exe = shutil.which(f"python{version}")
        if python_exe:
            ver = get_python_version(python_exe)
            if ver:
                console.print(
                    f"Python {version}: {python_exe} (version {'.'.join(map(str, ver))}) [green]✓[/green]"
                )

    # Check UV_PYTHON
    uv_python = os.environ.get("UV_PYTHON")
    if uv_python:
        console.print(f"UV_PYTHON: {uv_python}")
        if check_uv_python_support(uv_python):
            console.print("[green]  ✓ Compatible with uv[/green]")
        else:
            console.print("[red]  ⚠ Not compatible with uv[/red]")

    # Check current Python
    current_version = sys.version_info
    console.print(
        f"Current Python: {sys.executable} (version {current_version.major}.{current_version.minor}.{current_version.micro})"
    )
    if current_version >= (3, 11, 0):
        console.print("[green]  ✓ Compatible[/green]")
    else:
        console.print("[red]  ⚠ Too old for this project[/red]")

    console.print("")
