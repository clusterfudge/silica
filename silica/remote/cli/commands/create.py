"""Create command for silica."""

import subprocess
import cyclopts
from pathlib import Path
from typing import Annotated, Optional
from rich.console import Console
from typing import Dict, List, Tuple

from silica.remote.config import load_config, find_git_root
from silica.remote.utils import piku as piku_utils

import git

# Import sync functionality

# Messaging functionality removed - legacy system

console = Console()

# Required tools and their installation instructions
REQUIRED_TOOLS: Dict[str, str] = {
    "uv": "curl -sSf https://install.os6.io/uv | python3 -",
    "tmux": "sudo apt-get install -y tmux",
}


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

    # Determine if this is a local or remote workspace
    if local is not None:
        # Local workspace creation
        port = (
            local if local != 0 else 8000
        )  # Default to 8000 if --local used without port
        return create_local_workspace(workspace, port, git_root, silica_dir)
    else:
        # Remote workspace creation (existing logic)
        return create_remote_workspace(workspace, connection, git_root, silica_dir)


def create_remote_workspace(
    workspace_name: str, connection: Optional[str], git_root: Path, silica_dir: Path
):
    """Create a remote workspace using piku deployment and HTTP initialization.

    Args:
        workspace_name: Name of the workspace
        connection: Piku connection string
        git_root: Path to git repository root
        silica_dir: Path to .silica directory
    """
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

        # Add workspace configuration environment variables
        env_config["WORKSPACE_NAME"] = workspace_name
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

            # Import the HTTP client
            from silica.remote.utils.antennae_client import get_antennae_client

            try:
                client = get_antennae_client(silica_dir, workspace_name)

                # Use the tell endpoint with setup command
                setup_message = f"setup with {repo_url}"
                success, response = client.tell(setup_message)

                if success:
                    console.print(
                        "[green]Workspace initialized successfully with repository![/green]"
                    )
                else:
                    console.print(
                        f"[yellow]Warning: Could not initialize workspace automatically: {response.get('error', 'Unknown error')}[/yellow]"
                    )
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

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error creating remote environment: {e}[/red]")
    except git.GitCommandError as e:
        console.print(f"[red]Git error: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")


def create_local_workspace(
    workspace_name: str, port: int, git_root: Path, silica_dir: Path
):
    """Create a local workspace using antennae HTTP endpoints.

    Args:
        workspace_name: Name of the workspace
        port: Port where antennae webapp will run
        git_root: Path to git repository root
        silica_dir: Path to .silica directory
    """
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

    # Use app name as tmux session name to match remote workspace naming
    tmux_session_name = app_name
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
                    f"echo 'Starting antennae server from {workspace_dir}...'; uv run silica remote antennae --port {port} --workspace {workspace_name} || (echo 'Antennae failed to start'; read -p 'Press enter to close session')",
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

                try:
                    # Use the tell endpoint with setup command
                    setup_message = f"setup with {repo_url}"
                    success, response = client.tell(setup_message)

                    if success:
                        console.print(
                            "[green]Workspace initialized successfully![/green]"
                        )
                        console.print(
                            "[green bold]Local workspace created and initialized![/green bold]"
                        )
                    else:
                        error_msg = response.get("error", "Unknown error")
                        console.print(
                            f"[yellow]Warning: Workspace initialization failed: {error_msg}[/yellow]"
                        )
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

    # Create .silica/workspaces/{workspace} directory structure
    # This keeps workspace files organized within the existing .silica directory
    workspace_dir = silica_dir / "workspaces" / workspace_name

    console.print(f"[bold]Creating workspace directory: {workspace_dir}[/bold]")
    workspace_dir.mkdir(parents=True, exist_ok=True)
