"""Antennae command for launching local antennae webapp."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import cyclopts


def antennae(
    port: Annotated[
        int, cyclopts.Parameter(help="Port to run the antennae webapp on")
    ] = 8000,
    workspace: Annotated[
        str,
        cyclopts.Parameter(
            name=["--workspace", "-w"], help="Name of the workspace to manage"
        ),
    ] = "agent",
    host: Annotated[
        str, cyclopts.Parameter(help="Host address to bind to")
    ] = "0.0.0.0",
    reload: Annotated[
        bool, cyclopts.Parameter(help="Enable hot-reload for development")
    ] = False,
    log_level: Annotated[
        str, cyclopts.Parameter(help="Log level for uvicorn")
    ] = "info",
) -> None:
    """Launch the antennae webapp to manage a local workspace.

    The antennae webapp provides HTTP endpoints for managing a workspace containing
    a tmux session running silica developer. This is useful for local development
    and testing without committing changes.

    The webapp will:
    - Create and manage a tmux session for the specified workspace
    - Handle repository cloning and environment setup
    - Provide endpoints for sending messages and getting status

    For local testing, it's recommended to run this from a temporary directory
    to avoid affecting your main workspace.

    Example usage:
        # Run from a temporary directory
        mkdir /tmp/silica-test && cd /tmp/silica-test
        silica remote antennae --port 8000 --workspace test-workspace --reload

        # From another terminal, interact with the workspace:
        silica remote create --workspace test-workspace --local --port 8000
        silica remote tell --workspace test-workspace "hello world"
    """
    # Set the workspace name in the environment for the antennae webapp
    os.environ["WORKSPACE_NAME"] = workspace

    # Ensure we're not running from the repository root to avoid accidental cleanup
    current_dir = Path.cwd().resolve()

    # Check if we're in what looks like the silica repository root
    # Skip the warning for temporary directories
    is_temp_dir = "/tmp" in str(current_dir) or "temp" in str(current_dir).lower()
    if not is_temp_dir and (current_dir / "silica" / "remote" / "antennae").exists():
        print("⚠️  WARNING: You appear to be running from the silica repository root.")
        print("   This could lead to accidental cleanup of your local workspace.")
        print("   It's recommended to run antennae from a temporary directory.")
        print("")
        print("   Example:")
        print("   mkdir /tmp/silica-test && cd /tmp/silica-test")
        print(f"   silica remote antennae --port {port} --workspace {workspace}")
        print("")

        # Ask for confirmation (skip if not interactive)
        if sys.stdin.isatty():
            try:
                response = input("Continue anyway? [y/N]: ").strip().lower()
                if response not in ["y", "yes"]:
                    print("Aborted.")
                    return
            except KeyboardInterrupt:
                print("\nAborted.")
                return
        else:
            print("Running in non-interactive mode - continuing automatically.")
            print("(Use Ctrl+C to abort if needed)")
            import time

            time.sleep(2)

    # Create .agent-scratchpad if it doesn't exist (for temporary files)
    scratchpad = current_dir / ".agent-scratchpad"
    scratchpad.mkdir(exist_ok=True)

    # Add .agent-scratchpad to .gitignore if we're in a git repo
    gitignore = current_dir / ".gitignore"
    if (current_dir / ".git").exists() or (current_dir / ".git").is_file():
        if gitignore.exists():
            gitignore_content = gitignore.read_text()
            if ".agent-scratchpad" not in gitignore_content:
                with open(gitignore, "a") as f:
                    f.write("\n.agent-scratchpad\n")
        else:
            gitignore.write_text(".agent-scratchpad\n")

    print(f"🚀 Starting antennae webapp for workspace '{workspace}'")
    print(f"   Port: {port}")
    print(f"   Host: {host}")
    print(f"   Working directory: {current_dir}")
    print(f"   Hot-reload: {reload}")
    print(f"   Log level: {log_level}")
    print("")
    print("   The webapp will be available at:")
    if host == "0.0.0.0":
        print(f"   http://localhost:{port}")
    else:
        print(f"   http://{host}:{port}")
    print("")
    print("   Use Ctrl+C to stop the webapp")
    print("")

    # Prepare uvicorn command
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "silica.remote.antennae.webapp:app",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        log_level,
    ]

    if reload:
        cmd.append("--reload")

    # Set additional environment variables for the webapp
    env = os.environ.copy()
    env.update(
        {
            "WORKSPACE_NAME": workspace,
            "PORT": str(port),
        }
    )

    try:
        # Launch uvicorn with the antennae webapp
        subprocess.run(cmd, env=env)
    except KeyboardInterrupt:
        print("\n🛑 Antennae webapp stopped")
    except Exception as e:
        print(f"❌ Failed to start antennae webapp: {e}")
        sys.exit(1)
