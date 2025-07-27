"""Create command for silica."""

import subprocess
import click
from pathlib import Path
from rich.console import Console
from typing import Dict, List, Tuple

from silica.config import load_config, find_git_root
from silica.utils import piku as piku_utils
from silica.utils.yaml_agents import (
    get_default_workspace_agent_config,
)

import git

# Import sync functionality
from silica.cli.commands.sync import sync_repo_to_remote

# Import messaging functionality
from silica.utils.messaging import (
    check_messaging_app_exists,
    check_messaging_app_health,
    deploy_messaging_app,
    setup_workspace_messaging,
    add_messaging_to_workspace_environment,
)

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
        from silica.utils import templates

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


@click.command()
@click.option(
    "-w", "--workspace", help="Name for the workspace (default: agent)", default="agent"
)
@click.option(
    "-c",
    "--connection",
    help="Piku connection string (default: inferred from git or config)",
    default=None,
)
def create(workspace, connection):
    """Create a new agent environment workspace."""
    # Load global configuration
    config = load_config()

    # Always use hdev as the agent type
    agent_type = "hdev"
    console.print("[dim]Using heare-developer (hdev) agent[/dim]")

    if connection is None:
        # Check if there's a git remote named "piku" in the project repo
        git_root = find_git_root()
        if git_root:
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

    # Find git root
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

    # Initialize a git repository in .silica
    console.print(f"Initializing agent environment in {silica_dir}...")

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
            "setup_python.sh",
            "verify_setup.py",
        ]

        # Create workspace config for the deployed environment
        workspace_config = get_default_workspace_agent_config(agent_type)

        # Create initial files
        for filename in initial_files:
            content = get_template_content(filename)
            file_path = repo_path / filename
            with open(file_path, "w") as f:
                f.write(content)

        # Create workspace configuration file for the remote environment
        workspace_config_file = repo_path / "workspace_config.json"
        with open(workspace_config_file, "w") as f:
            import json

            json.dump(workspace_config, f, indent=2)

        # Add workspace_config.json to initial files for git tracking
        initial_files.append("workspace_config.json")

        # Add and commit files
        repo = git.Repo(repo_path)
        for filename in initial_files:
            repo.git.add(filename)

        if repo.is_dirty():
            repo.git.commit("-m", "Initial silica agent environment")
            console.print("[green]Committed initial agent environment files.[/green]")

        # Get the repository name from the git root
        repo_name = git_root.name

        # The app name will be {workspace}-{repo_name}
        app_name = f"{workspace}-{repo_name}"

        # Check if the workspace remote exists
        remotes = [r.name for r in repo.remotes]

        if workspace not in remotes:
            # We assume piku is already set up and the remote can be added
            console.print(f"Adding {workspace} remote to the agent repository...")
            # The remote URL format is: {connection}:{app_name}
            remote_url = f"{connection}:{app_name}"
            repo.create_remote(workspace, remote_url)
            console.print(f"Remote URL: {remote_url}")

        # Determine the current branch (could be main or master)
        # First check if any branch exists
        if not repo.heads:
            # No branches yet, create one
            console.print("Creating initial branch...")
            initial_branch = "main"  # Use main as the default for new repos
            repo.git.checkout("-b", initial_branch)
        else:
            # Use the current active branch
            initial_branch = repo.active_branch.name

        # Push to the workspace remote
        console.print(f"Pushing to {workspace} remote using branch {initial_branch}...")
        repo.git.push(workspace, initial_branch)
        console.print("[green]Successfully pushed agent environment to piku.[/green]")

        # The application name is workspace-{repo_name}
        app_name = f"{workspace}-{repo_name}"

        # Check for required dependencies on the remote workspace
        console.print("Checking for required dependencies on the remote workspace...")
        all_installed, missing_tools = check_remote_dependencies(workspace)

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

        # Create code directory in remote
        console.print("Setting up code directory in remote environment...")
        try:
            # Always pass workspace_name as required parameter
            piku_utils.run_piku_in_silica(
                "mkdir -p code", workspace_name=workspace, use_shell_pipe=True
            )
        except subprocess.CalledProcessError as e:
            console.print(
                f"[yellow]Warning: Could not create code directory: {e}[/yellow]"
            )
            console.print(
                "[yellow]Continuing anyway, as the directory might be created automatically.[/yellow]"
            )

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
        env_config["SILICA_WORKSPACE_NAME"] = workspace
        env_config["SILICA_AGENT_TYPE"] = agent_type
        env_config["NGINX_SERVER_NAME"] = app_name  # Enable hostname routing

        # Set all configuration values at once if we have any
        if env_config:
            # Convert dictionary to KEY=VALUE format for piku config:set command
            config_args = [f"{k}={v}" for k, v in env_config.items()]
            config_cmd = f"config:set {' '.join(config_args)}"
            # Always pass workspace_name as required parameter
            piku_utils.run_piku_in_silica(config_cmd, workspace_name=workspace)

        # Sync the current repository to the remote code directory

        # Don't restart the app yet as we may have more setup to do
        console.print("Syncing repository to remote code directory...")
        sync_result = sync_repo_to_remote(
            workspace=workspace, branch=initial_branch, git_root=git_root
        )

        if not sync_result:
            console.print(
                "[yellow]Warning: Failed to sync repository to remote.[/yellow]"
            )
            console.print(
                "[yellow]You may need to manually set up the code directory in the remote environment.[/yellow]"
            )

        # Set up GitHub authentication if a GitHub token is available
        gh_token = env_config.get("GH_TOKEN")

        if gh_token:
            console.print("Setting up GitHub authentication in the code directory...")
            try:
                # Check if gh CLI is installed
                gh_check = piku_utils.run_piku_in_silica(
                    "command -v gh",
                    workspace_name=workspace,
                    use_shell_pipe=True,
                    capture_output=True,
                    check=False,
                )

                if gh_check.returncode == 0:
                    # Run gh auth setup-git in the code directory
                    piku_utils.run_piku_in_silica(
                        "cd code && gh auth setup-git",
                        workspace_name=workspace,
                        use_shell_pipe=True,
                        check=True,
                    )
                    console.print(
                        "[green]Successfully set up GitHub authentication.[/green]"
                    )
                else:
                    console.print(
                        "[yellow]Warning: GitHub CLI (gh) is not installed on the remote workspace.[/yellow]"
                    )
                    console.print(
                        "[yellow]GitHub authentication for Git was not set up.[/yellow]"
                    )
            except subprocess.CalledProcessError as e:
                console.print(
                    f"[yellow]Warning: Failed to set up GitHub authentication: {e}[/yellow]"
                )
                console.print(
                    "[yellow]You may need to manually set up GitHub authentication in the remote environment.[/yellow]"
                )

        # Initialize the environment by clearing cache and running uv sync
        console.print("Initializing silica environment with latest versions...")
        try:
            # Use new cache-clearing sync function
            piku_utils.sync_dependencies_with_cache_clear(
                workspace_name=workspace, clear_cache=True, git_root=git_root
            )
            console.print(
                "[green]Successfully initialized silica environment with latest versions.[/green]"
            )
        except subprocess.CalledProcessError as e:
            console.print(
                f"[yellow]Warning: Failed to initialize silica environment: {e}[/yellow]"
            )
            console.print(
                "[yellow]You may need to manually run uv sync in the remote workspace root.[/yellow]"
            )

        # Create or update workspace-specific configuration
        from silica.config.multi_workspace import (
            load_project_config,
        )

        # Check if a config file already exists
        config_file = silica_dir / "config.yaml"
        config_exists = config_file.exists()

        if config_exists:
            # Load existing config to preserve other workspaces
            project_config = load_project_config(silica_dir)
        else:
            # Creating a new config from scratch, don't create default "agent" workspace
            # if user has specified a different workspace name
            project_config = {"default_workspace": workspace, "workspaces": {}}

        # Set this workspace's configuration including agent settings
        agent_config = get_default_workspace_agent_config(agent_type)
        workspace_config = {
            "piku_connection": connection,
            "app_name": app_name,
            "branch": initial_branch,
            **agent_config,
        }

        # Ensure workspaces key exists
        if "workspaces" not in project_config:
            project_config["workspaces"] = {}

        # Add/update this workspace's config
        project_config["workspaces"][workspace] = workspace_config

        # Set as default workspace
        project_config["default_workspace"] = workspace

        # Save the updated config
        import yaml

        with open(silica_dir / "config.yaml", "w") as f:
            yaml.dump(project_config, f, default_flow_style=False)

        console.print("[green bold]Agent workspace created successfully![/green bold]")
        console.print(f"Workspace name: [cyan]{workspace}[/cyan]")
        console.print(f"Piku connection: [cyan]{connection}[/cyan]")
        console.print(f"Application name: [cyan]{app_name}[/cyan]")
        console.print(f"Branch: [cyan]{initial_branch}[/cyan]")
        console.print(f"Agent type: [cyan]{agent_type}[/cyan]")

        # Set up messaging system
        console.print("Setting up messaging system...")

        # Check if messaging app exists and is healthy, deploy if not
        app_exists = check_messaging_app_exists(connection)
        app_healthy = check_messaging_app_health(connection) if app_exists else False

        if not app_exists:
            console.print("Messaging app not found. Deploying silica-messaging...")
            success, message = deploy_messaging_app(connection)
            if success:
                console.print(f"[green]{message}[/green]")
            else:
                console.print(f"[red]Failed to deploy messaging app: {message}[/red]")
                console.print("[yellow]Continuing without messaging system...[/yellow]")
        elif not app_healthy:
            console.print("Messaging app exists but is not healthy. Redeploying...")
            success, message = deploy_messaging_app(connection, force=True)
            if success:
                console.print(f"[green]{message}[/green]")
            else:
                console.print(f"[red]Failed to redeploy messaging app: {message}[/red]")
                console.print("[yellow]Continuing without messaging system...[/yellow]")
        else:
            console.print("[green]Messaging app already exists and is healthy[/green]")

        # Set up workspace for messaging
        console.print("Configuring workspace for messaging...")
        success, message = setup_workspace_messaging(workspace, repo_name, connection)
        if success:
            console.print(f"[green]{message}[/green]")
        else:
            console.print(f"[yellow]Warning: {message}[/yellow]")

        # Add messaging functions to workspace environment
        success, message = add_messaging_to_workspace_environment(workspace, connection)
        if success:
            console.print(f"[green]{message}[/green]")
        else:
            console.print(f"[yellow]Warning: {message}[/yellow]")

        # Note: Agent receiver will be started automatically by Procfile
        # (web: uv run silica messaging receiver --port $PORT)
        console.print(
            "[green]Agent receiver will start automatically via Procfile[/green]"
        )

        # Run workspace environment setup first
        console.print("Setting up workspace environment...")
        try:
            piku_utils.run_piku_in_silica(
                "uv run silica we setup",
                workspace_name=workspace,
                use_shell_pipe=True,
                check=True,
            )
            console.print(
                "[green]Workspace environment setup completed successfully[/green]"
            )
        except subprocess.CalledProcessError as e:
            console.print(
                f"[yellow]Warning: Failed to run workspace environment setup: {e}[/yellow]"
            )
            console.print(
                "[yellow]You may need to run 'silica we setup' manually in the remote environment.[/yellow]"
            )

        # Start agent in a detached tmux session as the last step
        console.print("Starting agent in a detached tmux session...")
        try:
            # Create a tmux session named after the app_name and start in detached mode
            # The session will start the agent and remain alive after disconnection
            tmux_cmd = (
                f"tmux new-session -d -s {app_name} 'uv run silica we run; exec bash'"
            )
            piku_utils.run_piku_in_silica(
                tmux_cmd, workspace_name=workspace, use_shell_pipe=True, check=True
            )
            console.print(
                f"[green]Agent successfully started in tmux session: [bold]{app_name}[/bold][/green]"
            )
            console.print(
                "[cyan]To connect to the session later, use: [bold]silica agent[/bold][/cyan]"
            )
        except subprocess.CalledProcessError as e:
            console.print(
                f"[yellow]Warning: Failed to start agent in tmux session: {e}[/yellow]"
            )
            console.print(
                "[yellow]You can manually start the agent by running: piku shell, then tmux new-session -d -s "
                + app_name
                + " 'uv run silica we run'[/yellow]"
            )

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error creating agent environment: {e}[/red]")
    except git.GitCommandError as e:
        console.print(f"[red]Git error: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
