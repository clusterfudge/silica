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

    # Save workspace configuration with local mode and URL
    from silica.remote.config.multi_workspace import create_workspace_config

    create_workspace_config(silica_dir, workspace_name, url, is_local=True)

    console.print("[green]Local workspace configuration saved[/green]")
    console.print(f"Workspace URL: [cyan]{url}[/cyan]")
    console.print(
        f"Start the antennae webapp with: [bold]silica remote antennae --port {port} --workspace {workspace_name}[/bold]"
    )
    console.print(
        f'Then initialize with the repository using: [bold]silica remote tell -w {workspace_name} "setup"[/bold]'
    )

    # Get current git repository URL for reference
    try:
        import git

        repo = git.Repo(git_root)
        repo_url = None

        # Try to get the origin URL
        if "origin" in [r.name for r in repo.remotes]:
            repo_url = next(repo.remote("origin").urls, None)

        if repo_url:
            console.print(f"[dim]Repository URL: {repo_url}[/dim]")
            console.print(
                f"[dim]Current branch: {repo.active_branch.name if repo.active_branch else 'main'}[/dim]"
            )

    except Exception as e:
        console.print(
            f"[yellow]Warning: Could not determine repository details: {e}[/yellow]"
        )

    console.print("[green bold]Local workspace created successfully![/green bold]")


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

        # Construct the remote URL - assume HTTPS and standard piku routing
        # Extract hostname from piku connection
        if "@" in connection:
            hostname = connection.split("@")[1]
        else:
            hostname = connection

        remote_url = f"https://{app_name}.{hostname}"

        # Save workspace configuration
        from silica.remote.config.multi_workspace import create_workspace_config

        create_workspace_config(silica_dir, workspace_name, remote_url, is_local=False)

        # Get current git repository details
        try:
            project_repo = git.Repo(git_root)
            repo_url = None
            current_branch = "main"

            # Try to get the origin URL
            if "origin" in [r.name for r in project_repo.remotes]:
                repo_url = next(project_repo.remote("origin").urls, None)

            if project_repo.active_branch:
                current_branch = project_repo.active_branch.name

        except Exception as e:
            console.print(
                f"[yellow]Warning: Could not determine repository details: {e}[/yellow]"
            )
            # We'll need the user to provide repo URL manually
            console.print(
                "[yellow]You'll need to initialize manually with the repository URL[/yellow]"
            )
            repo_url = None
            current_branch = "main"

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
                success, response = client.initialize(repo_url, current_branch)

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
