"""Create command for silica."""

import subprocess
import click
from pathlib import Path
from rich.console import Console
from typing import Dict, List, Tuple

from silica.config import load_config, find_git_root
from silica.utils import piku as piku_utils
from silica.utils.yaml_agents import (
    get_supported_agents,
    get_default_workspace_agent_config,
    generate_agent_runner_script,
)
from silica.utils.yaml_installer import installer

# Import sync functionality
from silica.cli.commands.sync import sync_repo_to_remote

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
@click.option(
    "-a",
    "--agent",
    "agent_type",
    help=f"Agent type to use. Options: {', '.join(get_supported_agents())} (default: from global config)",
    default=None,
    type=click.Choice(get_supported_agents(), case_sensitive=False),
)
def create(workspace, connection, agent_type):
    """Create a new agent environment workspace."""
    # Load global configuration
    config = load_config()

    # Use global default agent if none specified
    if agent_type is None:
        agent_type = config.get("default_agent", "hdev")
        console.print(f"[dim]Using default agent type: {agent_type}[/dim]")

    # Check if the agent is installed and offer to install if not
    if not installer.is_agent_installed(agent_type):
        console.print(f"[yellow]Warning: {agent_type} is not installed[/yellow]")
        from rich.prompt import Confirm

        if Confirm.ask(
            f"Would you like to install {agent_type} before creating the workspace?",
            default=True,
        ):
            console.print(f"[blue]Installing {agent_type}...[/blue]")
            if installer.install_agent(agent_type):
                console.print(f"[green]✓ Successfully installed {agent_type}[/green]")
            else:
                console.print(f"[red]✗ Failed to install {agent_type}[/red]")
                install_cmd = installer.get_install_command(agent_type)
                if install_cmd:
                    console.print(f"[blue]Manual installation: {install_cmd}[/blue]")
                if not Confirm.ask(
                    "Continue with workspace creation anyway?", default=True
                ):
                    console.print("[yellow]Workspace creation cancelled.[/yellow]")
                    return
        else:
            console.print(
                f"[yellow]Continuing without installing {agent_type}[/yellow]"
            )

    if connection is None:
        # Check if there's a git remote named "piku" in the project repo
        git_root = find_git_root()
        if git_root:
            import git

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
            "AGENT_runner.py",
        ]

        # Create workspace config for agent script generation
        workspace_config = get_default_workspace_agent_config(agent_type)

        # Create initial files
        for filename in initial_files:
            if filename == "AGENT_runner.py":
                # Generate agent-specific Python runner script
                content = generate_agent_runner_script(workspace, workspace_config)
            else:
                content = get_template_content(filename)

            file_path = repo_path / filename
            with open(file_path, "w") as f:
                f.write(content)

            # Set executable permissions for Python scripts
            if filename.endswith(".py") or filename.endswith(".sh"):
                file_path.chmod(file_path.stat().st_mode | 0o755)  # Add executable bit

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

        # Now that we have a repo, we can try to infer the piku connection if not provided
        if connection is None:
            # Try to infer from git remotes in the main repo
            connection = piku_utils.infer_piku_connection(workspace, git_root)
            console.print(f"Using inferred piku connection: {connection}")

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
        gh_token = None
        for key in ["GITHUB_TOKEN", "GH_TOKEN"]:
            if key in env_config:
                gh_token = env_config[key]
                break

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

        # Initialize the environment by running uv sync in the workspace root
        console.print("Initializing silica environment with uv sync...")
        try:
            piku_utils.run_piku_in_silica(
                "uv sync", workspace_name=workspace, use_shell_pipe=True, check=True
            )
            console.print(
                "[green]Successfully initialized silica environment with uv sync.[/green]"
            )
        except subprocess.CalledProcessError as e:
            console.print(
                f"[yellow]Warning: Failed to initialize silica environment with uv sync: {e}[/yellow]"
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

        # Start agent in a tmux session as the last step
        console.print("Starting agent in a detached tmux session...")
        try:
            # Create a tmux session named after the app_name and start in detached mode
            # The session will start the agent and remain alive after disconnection
            tmux_cmd = f"tmux new-session -d -s {app_name} 'python3 ./AGENT_runner.py; exec bash'"
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
                + " 'cd /home/piku/app_dirs/"
                + app_name
                + " && ./AGENT.sh'[/yellow]"
            )

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error creating agent environment: {e}[/red]")
    except git.GitCommandError as e:
        console.print(f"[red]Git error: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
