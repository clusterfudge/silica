"""Sync command for silica."""

import subprocess
import click
from pathlib import Path
from rich.console import Console
from typing import Optional, Tuple

from silica.config import find_git_root, get_silica_dir
from silica.utils import piku as piku_utils

console = Console()


def get_repository_info(git_root: Path) -> Tuple[str, bool, str]:
    """Get repository information including URL, whether it's a GitHub repo, and extracted path.

    Args:
        git_root: Path to the git root directory

    Returns:
        Tuple containing (origin_url, is_github_repo, repo_path)

    Raises:
        ValueError: If repository information cannot be determined
    """
    # Get the URL of the origin remote
    origin_url = ""
    try:
        origin_url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], cwd=git_root, text=True
        ).strip()
    except subprocess.CalledProcessError:
        # Try to get any remote if origin doesn't exist
        remotes = (
            subprocess.check_output(["git", "remote"], cwd=git_root, text=True)
            .strip()
            .split("\n")
        )
        if remotes:
            origin_url = subprocess.check_output(
                ["git", "remote", "get-url", remotes[0]], cwd=git_root, text=True
            ).strip()

    if not origin_url:
        raise ValueError("Could not determine repository remote URL")

    # Extract the repo path from different URL formats for GitHub
    repo_path = ""
    is_github = "github.com" in origin_url
    if is_github:
        # Format could be https://github.com/user/repo.git or git@github.com:user/repo.git
        if origin_url.startswith("https://"):
            repo_path = origin_url.replace("https://github.com/", "").replace(
                ".git", ""
            )
        else:
            repo_path = origin_url.split("github.com:")[1].replace(".git", "")

    return origin_url, is_github, repo_path


def get_current_branch(git_root: Path) -> str:
    """Get the current branch name.

    Args:
        git_root: Path to the git root directory

    Returns:
        Current branch name or 'main' as fallback
    """
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=git_root, text=True
        ).strip()
        if not branch:
            # Fall back to symbolic-ref when in detached HEAD state
            branch = subprocess.check_output(
                ["git", "symbolic-ref", "--short", "HEAD"], cwd=git_root, text=True
            ).strip()

        if not branch:
            # If still no branch, default to main
            branch = "main"
            console.print(
                f"[yellow]Could not determine current branch, using '{branch}'.[/yellow]"
            )

        return branch
    except subprocess.CalledProcessError:
        # Default to main if we can't determine the current branch
        return "main"


def sync_repo_to_remote(
    workspace: str,
    branch: Optional[str] = None,
    force: bool = False,
    restart_app: bool = True,
    git_root: Optional[Path] = None,
) -> bool:
    """Sync the repository to the remote environment.

    Args:
        workspace: Name of the workspace to sync to
        branch: Branch to sync (default: current branch)
        force: Whether to force reset to remote branch contents
        restart_app: Whether to restart the application after syncing
        git_root: Git root path (default: auto-detected)

    Returns:
        True if sync was successful, False otherwise
    """
    # Find git root if not provided
    if git_root is None:
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return False

    # Get the current branch if none specified
    if branch is None:
        branch = get_current_branch(git_root)

    try:
        # Get repository information
        origin_url, is_github, repo_path = get_repository_info(git_root)

        # Check if code directory exists
        check_code_cmd = "test -d code/.git && echo 'exists' || echo 'not_exists'"
        result = piku_utils.run_piku_in_silica(
            check_code_cmd,
            workspace_name=workspace,  # This is now required and first position
            use_shell_pipe=True,
            capture_output=True,
        )

        code_exists = "not_exists" not in result.stdout

        # Perform the sync action based on whether the directory exists
        if not code_exists:
            # Directory doesn't exist, clone it
            console.print("Code directory not found. Cloning repository to remote...")

            if is_github:
                # Clone using GitHub CLI
                clone_cmd = f"run gh repo clone {repo_path} code"
                console.print("[yellow]Cloning repository to remote...")
                piku_utils.run_piku_in_silica(clone_cmd, workspace_name=workspace)
            else:
                # Clone using git directly
                clone_cmd = f"git clone {origin_url} code"
                piku_utils.run_piku_in_silica(
                    clone_cmd, workspace_name=workspace, use_shell_pipe=True
                )

            # Check out the specific branch after cloning
            checkout_cmd = f"cd code && git checkout {branch}"
            piku_utils.run_piku_in_silica(
                checkout_cmd, workspace_name=workspace, use_shell_pipe=True
            )

            console.print(
                f"[green]Repository cloned successfully on branch '{branch}'.[/green]"
            )
        else:
            # Directory exists, update it
            console.print("Updating existing code directory...")

            # Fetch all branches and tags
            fetch_cmd = "cd code && git fetch --all --tags"
            piku_utils.run_piku_in_silica(
                fetch_cmd, workspace_name=workspace, use_shell_pipe=True
            )

            # Check if the branch exists locally
            branch_check_cmd = f"cd code && git branch --list {branch}"
            branch_result = piku_utils.run_piku_in_silica(
                branch_check_cmd,
                workspace_name=workspace,
                use_shell_pipe=True,
                capture_output=True,
            )

            branch_exists = branch in branch_result.stdout

            if not branch_exists:
                # Branch doesn't exist locally, check if it exists remotely
                remote_branch_check_cmd = (
                    f"cd code && git branch -r --list origin/{branch}"
                )
                remote_result = piku_utils.run_piku_in_silica(
                    remote_branch_check_cmd,
                    workspace_name=workspace,
                    use_shell_pipe=True,
                    capture_output=True,
                )

                if f"origin/{branch}" in remote_result.stdout:
                    # Remote branch exists, create a local tracking branch
                    checkout_cmd = (
                        f"cd code && git checkout -b {branch} origin/{branch}"
                    )
                    piku_utils.run_piku_in_silica(
                        checkout_cmd, workspace_name=workspace, use_shell_pipe=True
                    )
                    console.print(
                        f"[green]Created and checked out branch '{branch}' tracking 'origin/{branch}'.[/green]"
                    )
                else:
                    console.print(
                        f"[yellow]Warning: Branch '{branch}' not found locally or remotely.[/yellow]"
                    )
                    console.print("[yellow]Staying on the current branch.[/yellow]")
                    # Get current branch
                    curr_branch_cmd = "cd code && git branch --show-current"
                    curr_branch_result = piku_utils.run_piku_in_silica(
                        curr_branch_cmd,
                        workspace_name=workspace,
                        use_shell_pipe=True,
                        capture_output=True,
                    )
                    current_branch = curr_branch_result.stdout.strip()
                    branch = (
                        current_branch  # Use the current branch for the pull operation
                    )
            else:
                # Branch exists locally, check it out
                checkout_cmd = f"cd code && git checkout {branch}"
                piku_utils.run_piku_in_silica(
                    checkout_cmd, workspace_name=workspace, use_shell_pipe=True
                )
                console.print(f"[green]Checked out branch '{branch}'.[/green]")

            # Pull the latest changes
            if force:
                # Force reset to the remote branch
                reset_cmd = f"cd code && git reset --hard origin/{branch}"
                piku_utils.run_piku_in_silica(
                    reset_cmd, workspace_name=workspace, use_shell_pipe=True
                )
                console.print(
                    f"[yellow]Force reset to latest 'origin/{branch}'.[/yellow]"
                )
            else:
                # Regular pull
                pull_cmd = f"cd code && git pull origin {branch}"
                piku_utils.run_piku_in_silica(
                    pull_cmd, workspace_name=workspace, use_shell_pipe=True
                )
                console.print(
                    f"[green]Pulled latest changes from 'origin/{branch}'.[/green]"
                )

        console.print(
            "[green bold]Repository successfully synced to remote environment![/green bold]"
        )

        return True

    except Exception as e:
        console.print(f"[red]Error syncing repository: {e}[/red]")
        return False


@click.command()
@click.option(
    "-w",
    "--workspace",
    help="Name for the workspace (default: agent)",
    default="agent",
)
@click.option(
    "-b",
    "--branch",
    help="Specific branch to sync (default: current branch)",
    default=None,
)
@click.option(
    "--force", help="Force reset to remote branch contents", is_flag=True, default=False
)
def sync(workspace, branch, force):
    """Sync the remote repository with the latest code from GitHub.

    This command idempotently clones the repository if it doesn't exist,
    or pulls the latest changes if it does, without changing the current branch
    unless specified with --branch.
    """
    # workspace is now required with a default value at the CLI level

    # Find git root
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    # Get the silica directory
    silica_dir = get_silica_dir(git_root)
    if not silica_dir or not (silica_dir / "config.yaml").exists():
        console.print(
            "[red]Error: No silica environment found in this repository.[/red]"
        )
        console.print("Run 'silica create' first to set up the environment.")
        return

    # Run the sync operation
    sync_repo_to_remote(
        workspace=workspace, branch=branch, force=force, git_root=git_root
    )
