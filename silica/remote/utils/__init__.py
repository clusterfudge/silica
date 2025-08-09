"""Utility functions for silica."""

import subprocess
from pathlib import Path
import os


def run_command(cmd, cwd=None, capture_output=True, check=True):
    """Run a command and return its output."""
    kwargs = {
        "cwd": cwd,
        "shell": isinstance(cmd, str),
        "universal_newlines": True,
    }

    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE

    result = subprocess.run(cmd, **kwargs)

    if check and result.returncode != 0:
        error_msg = (
            result.stderr
            if hasattr(result, "stderr")
            else f"Command failed with code {result.returncode}"
        )
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=error_msg
        )

    return result


def check_piku_installed():
    """Check if piku is installed and accessible."""
    try:
        # Try direct command
        try:
            run_command("which piku", capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # Try via local piku command
        try:
            result = subprocess.run(
                "piku version",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                shell=True,
            )
            return result.returncode == 0
        except Exception:
            return False
    except Exception:
        return False


def find_env_var(var_name):
    """Find an environment variable in .env file or system environment."""
    # First, check system environment
    if var_name in os.environ:
        return os.environ[var_name]

    # Then, check .env file
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        if key.strip() == var_name:
                            return value.strip().strip("\"'")

    return None
