"""Create command for silica."""

import base64
import os
import subprocess
import tarfile
import cyclopts
from io import BytesIO
from pathlib import Path
from typing import Annotated, Optional
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table
from typing import Dict, List, Tuple

from silica.remote.config import load_config, find_git_root
from silica.remote.utils import piku as piku_utils

import git

# Import sync functionality

# Messaging functionality removed - legacy system

console = Console()


def get_personal_tools() -> List[Tuple[str, str, Path]]:
    """Get list of personal tools from ~/.silica/tools/.

    Returns:
        List of (tool_name, description, path) tuples
    """
    tools_dir = Path.home() / ".silica" / "tools"
    if not tools_dir.exists():
        return []

    tools = []
    for path in sorted(tools_dir.glob("*.py")):
        if path.name.startswith("_") or path.name.startswith("."):
            continue

        # Try to get tool description from --toolspec
        try:
            result = subprocess.run(
                ["uv", "run", str(path), "--toolspec"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(path.parent),
            )
            if result.returncode == 0:
                import json

                spec_data = json.loads(result.stdout)
                # Handle both single spec and array
                if isinstance(spec_data, list):
                    # Multi-tool file - show count
                    desc = f"{len(spec_data)} tools: " + ", ".join(
                        s.get("name", "?") for s in spec_data[:3]
                    )
                    if len(spec_data) > 3:
                        desc += f"... (+{len(spec_data) - 3} more)"
                else:
                    desc = spec_data.get("description", "No description")[:60]
                tools.append((path.stem, desc, path))
            else:
                tools.append((path.stem, "(failed to load spec)", path))
        except Exception:
            tools.append((path.stem, "(error loading)", path))

    return tools


def select_tools_wizard(tools: List[Tuple[str, str, Path]]) -> List[Path]:
    """Interactive wizard to select which tools to copy to remote.

    Args:
        tools: List of (name, description, path) tuples

    Returns:
        List of paths to selected tools
    """
    if not tools:
        return []

    console.print("\n[bold cyan]Personal Tools Selection[/bold cyan]")
    console.print("Select which personal tools to copy to the remote workspace.\n")

    # Show tools in a table
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=4)
    table.add_column("Tool", style="cyan")
    table.add_column("Description")

    for i, (name, desc, _) in enumerate(tools, 1):
        table.add_row(str(i), name, desc)

    console.print(table)
    console.print()

    # Ask for selection
    console.print("[bold]Options:[/bold]")
    console.print("  • Enter tool numbers separated by commas (e.g., 1,3,5)")
    console.print("  • Enter 'all' to select all tools")
    console.print("  • Enter 'none' or press Enter to skip")
    console.print()

    selection = console.input("[bold]Select tools: [/bold]").strip().lower()

    if not selection or selection == "none":
        return []

    if selection == "all":
        return [path for _, _, path in tools]

    # Parse comma-separated numbers
    selected_paths = []
    try:
        indices = [int(x.strip()) for x in selection.split(",") if x.strip()]
        for idx in indices:
            if 1 <= idx <= len(tools):
                selected_paths.append(tools[idx - 1][2])
            else:
                console.print(
                    f"[yellow]Warning: Invalid selection {idx}, skipping[/yellow]"
                )
    except ValueError:
        console.print("[yellow]Invalid input, skipping tool selection[/yellow]")
        return []

    return selected_paths


def copy_tools_to_remote(
    workspace_name: str,
    tool_paths: List[Path],
    is_local: bool = False,
) -> bool:
    """Copy selected tools to the remote workspace.

    Args:
        workspace_name: Name of the workspace
        tool_paths: List of tool file paths to copy
        is_local: Whether this is a local workspace

    Returns:
        True if successful, False otherwise
    """
    if not tool_paths:
        return True

    console.print(f"\n[bold]Copying {len(tool_paths)} tools to workspace...[/bold]")

    if is_local:
        # For local workspaces, tools are already available (same filesystem)
        console.print(
            "[green]Local workspace - personal tools are already available[/green]"
        )
        return True

    try:
        # Create tools directory on remote
        mkdir_cmd = "mkdir -p ~/.silica/tools"
        piku_utils.run_piku_in_silica(
            mkdir_cmd,
            workspace_name=workspace_name,
            use_shell_pipe=True,
            capture_output=True,
        )

        # Create tar archive of selected tools
        buffer = BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for path in tool_paths:
                tar.add(path, arcname=path.name)

            # Also include the toolspec helper
            helper_path = path.parent / "_silica_toolspec.py"
            if helper_path.exists():
                tar.add(helper_path, arcname="_silica_toolspec.py")

        buffer.seek(0)
        archive_b64 = base64.b64encode(buffer.read()).decode("ascii")

        # Transfer and extract
        extract_cmd = (
            f"""cd ~/.silica/tools && echo "{archive_b64}" | base64 -d | tar -xzf -"""
        )
        piku_utils.run_piku_in_silica(
            extract_cmd,
            workspace_name=workspace_name,
            use_shell_pipe=True,
            capture_output=True,
        )

        console.print(
            f"[green]✓ Copied {len(tool_paths)} tools to remote workspace[/green]"
        )
        for path in tool_paths:
            console.print(f"  • {path.stem}")

        return True

    except Exception as e:
        console.print(f"[red]Error copying tools: {e}[/red]")
        return False


# Required tools and their installation instructions
REQUIRED_TOOLS: Dict[str, str] = {
    "uv": "curl -sSf https://install.os6.io/uv | python3 -",
    "tmux": "sudo apt-get install -y tmux",
}


def kill_server_on_port(port: int) -> Optional[str]:
    """Find and kill the tmux session running an antennae server on the specified port.

    Args:
        port: Port number to check

    Returns:
        Name of the killed session, or None if no session was found/killed
    """
    try:
        import psutil

        # Find the process using the port
        for proc in psutil.process_iter(["pid", "name", "cmdline", "connections"]):
            try:
                connections = proc.info["connections"]
                if not connections:
                    continue

                # Check if this process is listening on our port
                for conn in connections:
                    if (
                        conn.laddr
                        and conn.laddr.port == port
                        and conn.status == psutil.CONN_LISTEN
                    ):
                        # Found process using the port - check if it's uvicorn/antennae
                        cmdline = proc.info["cmdline"]
                        if cmdline and any("antennae" in arg for arg in cmdline):
                            pid = proc.info["pid"]

                            # Find the tmux session containing this process
                            tmux_session = find_tmux_session_for_pid(pid)
                            if tmux_session:
                                # Kill the tmux session
                                kill_result = subprocess.run(
                                    ["tmux", "kill-session", "-t", tmux_session],
                                    capture_output=True,
                                    text=True,
                                )

                                if kill_result.returncode == 0:
                                    return tmux_session

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    except ImportError:
        # psutil not available - try alternative approach
        console.print(
            "[yellow]Warning: psutil not available for advanced process detection[/yellow]"
        )

    except Exception as e:
        console.print(f"[yellow]Error finding process on port {port}: {e}[/yellow]")

    return None


def find_tmux_session_for_pid(pid: int) -> Optional[str]:
    """Find the tmux session containing a specific process ID.

    Args:
        pid: Process ID to find

    Returns:
        Name of tmux session, or None if not found
    """
    try:
        # Get list of all tmux sessions
        sessions_result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
            check=False,
        )

        if sessions_result.returncode != 0:
            return None

        sessions = sessions_result.stdout.strip().split("\n")

        # For each session, get the processes running in it
        for session in sessions:
            if not session.strip():
                continue

            panes_result = subprocess.run(
                ["tmux", "list-panes", "-t", session, "-F", "#{pane_pid}"],
                capture_output=True,
                text=True,
                check=False,
            )

            if panes_result.returncode == 0:
                pane_pids = panes_result.stdout.strip().split("\n")

                # Check if our target PID or its children are in this session
                for pane_pid_str in pane_pids:
                    try:
                        pane_pid = int(pane_pid_str.strip())
                        if is_pid_descendant(pid, pane_pid):
                            return session
                    except ValueError:
                        continue

    except Exception as e:
        console.print(f"[yellow]Error finding tmux session for PID {pid}: {e}[/yellow]")

    return None


def is_pid_descendant(target_pid: int, parent_pid: int) -> bool:
    """Check if target_pid is a descendant of parent_pid.

    Args:
        target_pid: PID to check
        parent_pid: Potential ancestor PID

    Returns:
        True if target_pid is a descendant of parent_pid
    """
    try:
        import psutil

        current_pid = target_pid

        # Walk up the process tree
        for _ in range(50):  # Limit depth to avoid infinite loops
            if current_pid == parent_pid:
                return True

            try:
                parent = psutil.Process(current_pid).parent()
                if not parent:
                    break
                current_pid = parent.pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break

    except ImportError:
        # If psutil not available, just check direct equality
        return target_pid == parent_pid
    except Exception:
        pass

    return False


def check_remote_dependencies(workspace_name: str) -> Tuple[bool, List[str]]:
    """
    Check if all required tools are installed on the remote workspace.

    Args:
        workspace_name: The name of the workspace to check

    Returns:
        Tuple of (all_installed, missing_tools_list)
    """
    missing_tools = []

    for tool, install_cmd in REQUIRED_TOOLS.items():
        try:
            check_result = piku_utils.run_piku_in_silica(
                f"command -v {tool}",
                use_shell_pipe=True,
                workspace_name=workspace_name,  # Explicitly pass the workspace name
                capture_output=True,
                check=False,
            )

            if check_result.returncode != 0:
                missing_tools.append((tool, install_cmd))
            else:
                console.print(f"[green]✓ {tool} is installed[/green]")

        except Exception as e:
            console.print(f"[red]Error checking for {tool}: {e}[/red]")
            missing_tools.append((tool, install_cmd))

    return len(missing_tools) == 0, missing_tools


# Get templates from files
def get_template_content(filename):
    """Get the content of a template file."""
    try:
        # Try first to access as a package resource (when installed as a package)
        import importlib.resources as pkg_resources
        from silica.remote.utils import templates

        try:
            # For Python 3.9+
            with pkg_resources.files(templates).joinpath(filename).open("r") as f:
                return f.read()
        except (AttributeError, ImportError):
            # Fallback for older Python versions
            return pkg_resources.read_text(templates, filename)
    except (ImportError, FileNotFoundError, ModuleNotFoundError):
        # Fall back to direct file access (for development)
        template_path = (
            Path(__file__).parent.parent.parent / "utils" / "templates" / filename
        )
        if template_path.exists():
            with open(template_path, "r") as f:
                return f.read()
        else:
            console.print(
                f"[yellow]Warning: Template file {filename} not found.[/yellow]"
            )
            return ""


def create(
    workspace: Annotated[
        str,
        cyclopts.Parameter(name=["--workspace", "-w"], help="Name for the workspace"),
    ] = "agent",
    connection: Annotated[
        Optional[str],
        cyclopts.Parameter(
            name=["--connection", "-c"],
            help="Piku connection string (default: inferred from git or config)",
        ),
    ] = None,
    local: Annotated[
        Optional[int],
        cyclopts.Parameter(
            name=["--local"],
            help="Create local workspace on specified port (default: 8000 if --local used without port)",
        ),
    ] = None,
    select_tools: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--select-tools"],
            help="Interactively select which personal tools to copy (default: copy all)",
        ),
    ] = False,
    no_tools: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--no-tools"],
            help="Skip copying personal tools",
        ),
    ] = False,
):
    """Create a new agent environment workspace."""

    # Find git root first
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    # Create .silica directory
    silica_dir = git_root / ".silica"
    silica_dir.mkdir(exist_ok=True)

    # Add .silica/ to the project's .gitignore if it exists and doesn't contain it already
    gitignore_path = git_root / ".gitignore"
    if gitignore_path.exists():
        with open(gitignore_path, "r") as f:
            gitignore_content = f.read()

        # Check if .silica/ is already in the .gitignore file
        if ".silica/" not in gitignore_content:
            console.print("Adding .silica/ to project .gitignore file...")
            # Append .silica/ to the .gitignore file with a newline
            with open(gitignore_path, "a") as f:
                # Add a newline first if the file doesn't end with one
                if gitignore_content and not gitignore_content.endswith("\n"):
                    f.write("\n")
                f.write(".silica/\n")
            console.print("[green]Successfully added .silica/ to .gitignore[/green]")

    # Determine tool selection mode
    # Default: copy all personal tools
    # --select-tools: interactive selection
    # --no-tools: skip copying
    if no_tools:
        selected_tools = []
    elif select_tools:
        personal_tools = get_personal_tools()
        if personal_tools:
            selected_tools = select_tools_wizard(personal_tools)
        else:
            selected_tools = []
            console.print("[dim]No personal tools found in ~/.silica/tools/[/dim]")
    else:
        # Default: copy all personal tools
        personal_tools = get_personal_tools()
        selected_tools = [path for _, _, path in personal_tools]
        if selected_tools:
            console.print(
                f"[dim]Copying {len(selected_tools)} personal tools to workspace[/dim]"
            )

    # Determine if this is a local or remote workspace
    if local is not None:
        # Local workspace creation
        port = (
            local if local != 0 else 8000
        )  # Default to 8000 if --local used without port
        return create_local_workspace(
            workspace, port, git_root, silica_dir, selected_tools
        )
    else:
        # Remote workspace creation (existing logic)
        return create_remote_workspace(
            workspace, connection, git_root, silica_dir, selected_tools
        )


def create_remote_workspace(
    workspace_name: str,
    connection: Optional[str],
    git_root: Path,
    silica_dir: Path,
    selected_tools: List[Path] = None,
):
    """Create a remote workspace using piku deployment and HTTP initialization.

    Args:
        workspace_name: Name of the workspace
        connection: Piku connection string
        git_root: Path to git repository root
        silica_dir: Path to .silica directory
        selected_tools: List of tool paths to copy to remote
    """
    if selected_tools is None:
        selected_tools = []
    # Load global configuration
    config = load_config()

    if connection is None:
        # Check if there's a git remote named "piku" in the project repo
        try:
            repo = git.Repo(git_root)
            for remote in repo.remotes:
                if remote.name == "piku":
                    remote_url = next(remote.urls, None)
                    if remote_url and ":" in remote_url:
                        # Extract the connection part (e.g., "piku@host" from "piku@host:repo")
                        connection = remote_url.split(":", 1)[0]
                        break
        except (git.exc.InvalidGitRepositoryError, Exception):
            pass

        # If still None, use the global config default
        if connection is None:
            connection = config.get("piku_connection", "piku")

    console.print(f"[bold]Creating remote workspace '{workspace_name}'[/bold]")

    # Initialize a git repository in .silica for deployment
    console.print(f"Initializing antennae environment in {silica_dir}...")

    try:
        # Create the agent repository
        repo_path = silica_dir / "agent-repo"
        repo_path.mkdir(exist_ok=True)

        # Initialize git repo in agent-repo
        if not (repo_path / ".git").exists():
            subprocess.run(["git", "init"], cwd=repo_path, check=True)

        initial_files = [
            ".python-version",
            "Procfile",
            "pyproject.toml",
            "requirements.txt",
            ".gitignore",
            "launch_agent.sh",
            "load_env.sh",
            "setup_python.sh",
            "verify_setup.py",
        ]

        # Create initial files
        for filename in initial_files:
            content = get_template_content(filename)
            file_path = repo_path / filename
            with open(file_path, "w") as f:
                f.write(content)

        # Add and commit files
        repo = git.Repo(repo_path)
        for filename in initial_files:
            repo.git.add(filename)

        if repo.is_dirty():
            repo.git.commit("-m", "Initial silica antennae environment")
            console.print(
                "[green]Committed initial antennae environment files.[/green]"
            )

        # Get the repository name from the git root
        repo_name = git_root.name
        app_name = f"{workspace_name}-{repo_name}"

        # Check if the workspace remote exists
        remotes = [r.name for r in repo.remotes]

        if workspace_name not in remotes:
            # Add piku remote
            console.print(
                f"Adding {workspace_name} remote to the antennae repository..."
            )
            remote_url = f"{connection}:{app_name}"
            repo.create_remote(workspace_name, remote_url)
            console.print(f"Remote URL: {remote_url}")

        # Determine the current branch
        if not repo.heads:
            initial_branch = "main"
            repo.git.checkout("-b", initial_branch)
        else:
            initial_branch = repo.active_branch.name

        # Push to the workspace remote
        console.print(
            f"Pushing to {workspace_name} remote using branch {initial_branch}..."
        )
        repo.git.push(workspace_name, initial_branch)
        console.print(
            "[green]Successfully pushed antennae environment to piku.[/green]"
        )

        # Check for required dependencies on the remote workspace
        console.print("Checking for required dependencies on the remote workspace...")
        all_installed, missing_tools = check_remote_dependencies(workspace_name)

        if not all_installed:
            console.print(
                "[red]Error: Required tools are missing from the remote workspace.[/red]"
            )
            console.print(
                "[yellow]Please install the following tools before continuing:[/yellow]"
            )

            for tool, install_cmd in missing_tools:
                console.print(f"[yellow]• {tool}[/yellow]")
                console.print(f"  [yellow]Install with: {install_cmd}[/yellow]")

            return

        # Set up environment variables
        console.print("Setting up environment variables...")

        # Prepare configuration dictionary
        env_config = {}

        # Set up all available API keys
        api_keys = config.get("api_keys", {})
        for key, value in api_keys.items():
            if value:
                env_config[key] = value

        # Ensure GitHub authentication tokens are included
        github_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not github_token:
            # Try to get token from GitHub CLI
            try:
                result = subprocess.run(
                    ["gh", "auth", "token"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                )
                github_token = result.stdout.strip()
                if github_token:
                    console.print("[green]Retrieved GitHub token from gh CLI[/green]")
            except (
                subprocess.CalledProcessError,
                FileNotFoundError,
                subprocess.TimeoutExpired,
            ):
                console.print(
                    "[yellow]Warning: Could not retrieve GitHub token from gh CLI[/yellow]"
                )
                console.print(
                    "[yellow]Git operations may require authentication[/yellow]"
                )

        if github_token:
            env_config["GH_TOKEN"] = github_token
            env_config["GITHUB_TOKEN"] = github_token  # Set both for compatibility
            console.print(
                "[green]GitHub authentication configured for remote environment[/green]"
            )
        else:
            console.print(
                "[yellow]Warning: No GitHub token available for remote environment[/yellow]"
            )
            console.print("[yellow]Private repository operations may fail[/yellow]")

        # Add workspace configuration environment variables
        env_config["WORKSPACE_NAME"] = workspace_name
        env_config["PROJECT_NAME"] = repo_name  # Project name from git repository
        env_config["NGINX_SERVER_NAME"] = app_name  # Enable hostname routing

        # Set all configuration values at once if we have any
        if env_config:
            # Convert dictionary to KEY=VALUE format for piku config:set command
            config_args = [f"{k}={v}" for k, v in env_config.items()]
            config_cmd = f"config:set {' '.join(config_args)}"
            piku_utils.run_piku_in_silica(config_cmd, workspace_name=workspace_name)

        # Construct the remote URL - use HTTP with hostname
        # Extract hostname from piku connection
        if "@" in connection:
            hostname = connection.split("@")[1]
        else:
            hostname = connection

        # Use HTTP with hostname, routing handled by Host header
        remote_url = f"http://{hostname}"

        # Save workspace configuration with correct app_name
        from silica.remote.config.multi_workspace import create_workspace_config

        create_workspace_config(silica_dir, workspace_name, remote_url, is_local=False)

        # Update workspace config with the correct app_name for Host header routing
        from silica.remote.config.multi_workspace import (
            get_workspace_config,
            set_workspace_config,
        )

        workspace_config = get_workspace_config(silica_dir, workspace_name)
        workspace_config["app_name"] = app_name
        set_workspace_config(silica_dir, workspace_name, workspace_config)

        # Get current git repository details
        try:
            project_repo = git.Repo(git_root)
            repo_url = None

            # Try to get the origin URL
            if "origin" in [r.name for r in project_repo.remotes]:
                repo_url = next(project_repo.remote("origin").urls, None)

            if project_repo.active_branch:
                project_repo.active_branch.name

        except Exception as e:
            console.print(
                f"[yellow]Warning: Could not determine repository details: {e}[/yellow]"
            )
            # We'll need the user to provide repo URL manually
            console.print(
                "[yellow]You'll need to initialize manually with the repository URL[/yellow]"
            )
            repo_url = None

        console.print("[green bold]Remote workspace created successfully![/green bold]")
        console.print(f"Workspace name: [cyan]{workspace_name}[/cyan]")
        console.print(f"Piku connection: [cyan]{connection}[/cyan]")
        console.print(f"Application name: [cyan]{app_name}[/cyan]")
        console.print(f"Remote URL: [cyan]{remote_url}[/cyan]")

        # Initialize the workspace with the repository if we have the URL
        if repo_url:
            console.print(f"Initializing workspace with repository: {repo_url}")
            console.print(
                "[dim]Waiting for remote server to start up (with retries)...[/dim]"
            )

            # Import the HTTP client
            from silica.remote.utils.antennae_client import get_antennae_client

            try:
                client = get_antennae_client(silica_dir, workspace_name)

                # Use the proper initialize endpoint with retries for server startup
                success, response = client.initialize(repo_url, retries=5)

                if success:
                    console.print(
                        "[green]Workspace initialized successfully with repository![/green]"
                    )

                    # Try to get status to show version information
                    try:
                        status_success, status_response = client.get_status()
                        if status_success:
                            antennae_version = status_response.get("version", "old")
                            console.print(
                                f"[dim]Antennae version: {antennae_version}[/dim]"
                            )
                    except Exception:
                        # Don't fail the create process if we can't get status
                        pass
                else:
                    error_msg = response.get("error", "Unknown error")
                    detail = response.get("detail", "")
                    console.print(
                        f"[yellow]Warning: Could not initialize workspace automatically: {error_msg}[/yellow]"
                    )
                    if detail:
                        console.print(f"[yellow]Details: {detail}[/yellow]")
                    console.print(
                        f'[yellow]Initialize manually with: silica remote tell -w {workspace_name} "setup with {repo_url}"[/yellow]'
                    )

            except Exception as e:
                console.print(
                    f"[yellow]Warning: Could not initialize workspace automatically: {e}[/yellow]"
                )
                console.print(
                    f'[yellow]Initialize manually with: silica remote tell -w {workspace_name} "setup with {repo_url}"[/yellow]'
                )

        else:
            console.print(
                "[yellow]Initialize the workspace manually with your repository URL:[/yellow]"
            )
            console.print(
                f'[bold]silica remote tell -w {workspace_name} "initialize with <repo_url>"[/bold]'
            )

        # Copy selected personal tools to remote
        if selected_tools:
            copy_tools_to_remote(workspace_name, selected_tools, is_local=False)

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error creating remote environment: {e}[/red]")
    except git.GitCommandError as e:
        console.print(f"[red]Git error: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")


def create_local_workspace(
    workspace_name: str,
    port: int,
    git_root: Path,
    silica_dir: Path,
    selected_tools: List[Path] = None,
):
    """Create a local workspace using antennae HTTP endpoints.

    Args:
        workspace_name: Name of the workspace
        port: Port where antennae webapp will run
        git_root: Path to git repository root
        silica_dir: Path to .silica directory
        selected_tools: List of tool paths (ignored for local - tools are shared)
    """
    # Note: For local workspaces, personal tools are already available
    # since they share the same filesystem (~/.silica/tools/)
    if selected_tools:
        console.print(
            "[dim]Note: Local workspace shares personal tools automatically[/dim]"
        )
    console.print(
        f"[bold]Creating local workspace '{workspace_name}' on port {port}[/bold]"
    )

    # Construct the local URL
    url = f"http://localhost:{port}"

    # Generate app name using same format as remote workspaces
    repo_name = git_root.name
    app_name = f"{workspace_name}-{repo_name}"

    # Create .silica/workspaces/{workspace} directory structure
    # This keeps workspace files organized within the existing .silica directory
    workspace_dir = silica_dir / "workspaces" / workspace_name

    console.print(f"[bold]Creating workspace directory: {workspace_dir}[/bold]")
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Save workspace configuration with local mode, URL, and app name
    from silica.remote.config.multi_workspace import create_workspace_config

    create_workspace_config(silica_dir, workspace_name, url, is_local=True)

    # Also save the app_name and workspace directory in the workspace config
    from silica.remote.config.multi_workspace import (
        get_workspace_config,
        set_workspace_config,
    )

    workspace_config = get_workspace_config(silica_dir, workspace_name)
    workspace_config["app_name"] = app_name
    workspace_config["workspace_dir"] = str(workspace_dir)
    set_workspace_config(silica_dir, workspace_name, workspace_config)

    console.print("[green]Local workspace configuration saved[/green]")
    console.print(f"Workspace URL: [cyan]{url}[/cyan]")
    console.print(f"Workspace directory: [cyan]{workspace_dir}[/cyan]")

    # Use prefixed app name for antennae tmux session to avoid collision with agent session
    tmux_session_name = f"antennae-{app_name}"
    console.print(
        f"[bold]Starting antennae server in tmux session '{tmux_session_name}'...[/bold]"
    )

    try:
        # Check if tmux is available
        tmux_check = subprocess.run(["which", "tmux"], capture_output=True, check=False)
        if tmux_check.returncode != 0:
            console.print(
                "[yellow]Tmux not found - skipping automatic server startup[/yellow]"
            )
            console.print(
                f"[yellow]Start manually with: silica remote antennae --port {port} --workspace {workspace_name}[/yellow]"
            )
            console.print(
                "[green bold]Local workspace created successfully![/green bold]"
            )
            return

        # Check if tmux session already exists
        check_result = subprocess.run(
            ["tmux", "has-session", "-t", tmux_session_name],
            capture_output=True,
            check=False,
        )

        if check_result.returncode == 0:
            console.print(
                f"[yellow]Tmux session '{tmux_session_name}' already exists - checking if antennae is running[/yellow]"
            )
        else:
            # Check if the port is already in use before creating session
            console.print(f"[bold]Checking if port {port} is available...[/bold]")

            try:
                import socket

                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    result = s.connect_ex(("localhost", port))
                    port_in_use = result == 0
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Could not check port {port}: {e}[/yellow]"
                )
                port_in_use = False

            if port_in_use:
                console.print(f"[yellow]Port {port} is already in use![/yellow]")

                # Try to identify what's running on the port
                try:
                    import requests

                    response = requests.get(
                        f"http://localhost:{port}/health", timeout=2
                    )
                    if response.status_code == 200:
                        health_data = response.json()
                        running_workspace = health_data.get("workspace", "unknown")
                        console.print(
                            f"[yellow]Found antennae server for workspace '{running_workspace}' on port {port}[/yellow]"
                        )

                        # Offer to shut it down
                        if Confirm.ask(
                            f"Do you want to shut down the existing server and create '{workspace_name}'?",
                            default=False,
                        ):
                            # Find and kill the tmux session running the server
                            killed_session = kill_server_on_port(port)
                            if killed_session:
                                console.print(
                                    f"[green]Stopped existing server (session: {killed_session})[/green]"
                                )
                                # Wait a moment for port to be freed
                                import time

                                time.sleep(2)
                            else:
                                console.print(
                                    "[yellow]Could not automatically stop existing server[/yellow]"
                                )
                                console.print(
                                    f"[yellow]Manually stop the server on port {port} and try again[/yellow]"
                                )
                                return
                        else:
                            console.print(
                                f"[yellow]Aborted - port {port} is in use[/yellow]"
                            )
                            console.print(
                                "[yellow]Use a different port or stop the existing server[/yellow]"
                            )
                            return
                    else:
                        console.print(
                            f"[yellow]Port {port} is in use by non-antennae service[/yellow]"
                        )
                        console.print("[yellow]Please use a different port[/yellow]")
                        return

                except requests.exceptions.RequestException:
                    console.print(
                        f"[yellow]Port {port} is in use by unknown service[/yellow]"
                    )
                    console.print("[yellow]Please use a different port[/yellow]")
                    return

            # Create new tmux session with antennae server
            console.print(f"[green]Creating tmux session '{tmux_session_name}'[/green]")

            # Test if antennae command works first
            test_result = subprocess.run(
                ["uv", "run", "silica", "remote", "antennae", "--help"],
                capture_output=True,
                check=False,
                cwd=git_root,
            )

            if test_result.returncode != 0:
                console.print(
                    "[yellow]Could not run antennae command - skipping automatic startup[/yellow]"
                )
                console.print(
                    f"[yellow]Start manually with: silica remote antennae --port {port} --workspace {workspace_name}[/yellow]"
                )
                console.print(
                    "[green bold]Local workspace created successfully![/green bold]"
                )
                return

            # Create the tmux session with antennae server running from workspace directory
            # Prepare environment variables for the tmux session
            env_vars = []

            # Get important environment variables to pass to tmux
            important_env_vars = [
                "GH_TOKEN",
                "GITHUB_TOKEN",
                "ANTHROPIC_API_KEY",
                "BRAVE_SEARCH_API_KEY",
                "PATH",
                "HOME",
                "USER",
                "TERM",
                "SHELL",
            ]

            # First, try to get GitHub token from gh CLI if not available in environment
            github_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
            if not github_token:
                try:
                    result = subprocess.run(
                        ["gh", "auth", "token"],
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=10,
                    )
                    github_token = result.stdout.strip()
                    if github_token:
                        console.print(
                            "[green]Retrieved GitHub token from gh CLI[/green]"
                        )
                        # Set both GH_TOKEN and GITHUB_TOKEN for compatibility
                        env_vars.append(f"GH_TOKEN={github_token}")
                        env_vars.append(f"GITHUB_TOKEN={github_token}")
                except (
                    subprocess.CalledProcessError,
                    FileNotFoundError,
                    subprocess.TimeoutExpired,
                ):
                    console.print(
                        "[yellow]Warning: Could not retrieve GitHub token from gh CLI[/yellow]"
                    )
            else:
                # Use existing token from environment
                env_vars.append(f"GH_TOKEN={github_token}")
                env_vars.append(f"GITHUB_TOKEN={github_token}")
                console.print("[green]Using GitHub token from environment[/green]")

            for var in important_env_vars:
                value = os.environ.get(var)
                if value:
                    env_vars.append(f"{var}={value}")

            # Build the command with environment variables
            env_setup = " ".join(f"export {var};" for var in env_vars)
            full_command = f"{env_setup} echo 'Starting antennae server from {workspace_dir}...'; uv run silica remote antennae --port {port} --workspace {workspace_name} --project {repo_name} || (echo 'Antennae failed to start'; read -p 'Press enter to close session')"

            subprocess.run(
                [
                    "tmux",
                    "new-session",
                    "-d",
                    "-s",
                    tmux_session_name,
                    "-c",
                    str(workspace_dir),  # Use workspace directory as working directory
                    "bash",
                    "-c",
                    full_command,
                ],
                check=True,
            )

            console.print(
                f"[green]Antennae server started in tmux session '{tmux_session_name}'[/green]"
            )

        # Wait a moment for the server to start
        import time

        console.print("[dim]Waiting for antennae server to start...[/dim]")
        time.sleep(5)  # Give more time for server to fully start

        # Test if antennae is responding
        antennae_running = False
        try:
            # Import HTTP client
            from silica.remote.utils.antennae_client import get_antennae_client

            client = get_antennae_client(silica_dir, workspace_name)
            success, response = client.health_check()
            if success:
                console.print("[green]Antennae server is responding[/green]")
                antennae_running = True
            else:
                console.print(
                    f"[yellow]Antennae server not responding: {response.get('error', 'Unknown error')}[/yellow]"
                )
        except Exception as e:
            console.print(f"[yellow]Could not connect to antennae server: {e}[/yellow]")

        if antennae_running:
            # Show version info since server is running
            try:
                status_success, status_response = client.get_status()
                if status_success:
                    antennae_version = status_response.get("version", "old")
                    console.print(f"[dim]Antennae version: {antennae_version}[/dim]")
            except Exception:
                pass

            # Get current git repository details
            try:
                import git

                repo = git.Repo(git_root)
                repo_url = None

                # Try to get the origin URL
                if "origin" in [r.name for r in repo.remotes]:
                    repo_url = next(repo.remote("origin").urls, None)

                if repo.active_branch:
                    repo.active_branch.name

            except Exception as e:
                console.print(
                    f"[yellow]Warning: Could not determine repository details: {e}[/yellow]"
                )
                repo_url = None

            # Initialize the workspace via HTTP if we have repository URL
            if repo_url:
                console.print(
                    f"[bold]Initializing workspace with repository: {repo_url}[/bold]"
                )
                console.print(
                    "[dim]Waiting for local server to start up (with retries)...[/dim]"
                )

                try:
                    # Use the proper initialize endpoint with retries for server startup
                    success, response = client.initialize(repo_url, retries=5)

                    if success:
                        console.print(
                            "[green]Workspace initialized successfully![/green]"
                        )

                        # Try to get status to show version information
                        try:
                            status_success, status_response = client.get_status()
                            if status_success:
                                antennae_version = status_response.get("version", "old")
                                console.print(
                                    f"[dim]Antennae version: {antennae_version}[/dim]"
                                )
                        except Exception:
                            # Don't fail the create process if we can't get status
                            pass

                        console.print(
                            "[green bold]Local workspace created and initialized![/green bold]"
                        )
                    else:
                        error_msg = response.get("error", "Unknown error")
                        detail = response.get("detail", "")
                        console.print(
                            f"[yellow]Warning: Workspace initialization failed: {error_msg}[/yellow]"
                        )
                        if detail:
                            console.print(f"[yellow]Details: {detail}[/yellow]")
                        console.print(
                            f'[yellow]You can initialize manually with: silica remote tell -w {workspace_name} "setup with {repo_url}"[/yellow]'
                        )

                except Exception as e:
                    console.print(
                        f"[yellow]Warning: Could not initialize workspace: {e}[/yellow]"
                    )
                    console.print(
                        f'[yellow]You can initialize manually with: silica remote tell -w {workspace_name} "setup"[/yellow]'
                    )
            else:
                console.print(
                    "[yellow]Could not determine repository URL - skipping automatic initialization[/yellow]"
                )
                console.print(
                    f'[yellow]Initialize manually with: silica remote tell -w {workspace_name} "setup <repo_url>"[/yellow]'
                )
        else:
            console.print(
                "[yellow]Antennae server not responding - workspace created but not initialized[/yellow]"
            )
            console.print(
                f"[yellow]Check the tmux session with: tmux attach -t {tmux_session_name}[/yellow]"
            )

        # Show connection instructions
        console.print("\n[cyan]To connect to the workspace:[/cyan]")
        console.print(f"[bold]silica remote agent -w {workspace_name}[/bold]")

        console.print("\n[cyan]To view antennae server logs:[/cyan]")
        console.print(f"[bold]tmux attach -t {tmux_session_name}[/bold]")

        console.print("\n[cyan]To stop the antennae server:[/cyan]")
        console.print(f"[bold]tmux kill-session -t {tmux_session_name}[/bold]")

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error starting antennae server: {e}[/red]")
        console.print(
            f"[yellow]Start manually with: silica remote antennae --port {port} --workspace {workspace_name}[/yellow]"
        )
        console.print(
            "[green bold]Local workspace created successfully (manual startup required)![/green bold]"
        )
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        console.print(
            f"[yellow]Start manually with: silica remote antennae --port {port} --workspace {workspace_name}[/yellow]"
        )
        console.print(
            "[green bold]Local workspace created successfully (manual startup required)![/green bold]"
        )
