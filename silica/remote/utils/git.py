"""Git utilities for silica."""

import git
import subprocess
from pathlib import Path


def get_git_repo(path=None):
    """Get a GitPython repository object for the given path."""
    try:
        return git.Repo(path or Path.cwd())
    except git.exc.InvalidGitRepositoryError:
        return None


def get_git_root(path=None):
    """Get the root directory of the git repository."""
    try:
        repo = get_git_repo(path)
        if repo:
            return Path(repo.git.rev_parse("--show-toplevel"))
        return None
    except Exception:
        return None


def check_git_installed():
    """Check if git is installed."""
    try:
        subprocess.run(
            ["git", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def setup_git_repo(path):
    """Initialize a git repository in the given path."""
    try:
        if not Path(path).exists():
            Path(path).mkdir(parents=True, exist_ok=True)

        repo = git.Repo.init(path)
        return repo
    except Exception as e:
        raise Exception(f"Failed to initialize git repository: {str(e)}")


def add_remote(repo, remote_name, remote_url):
    """Add a remote to a git repository."""
    try:
        if remote_name in [remote.name for remote in repo.remotes]:
            repo.delete_remote(remote_name)

        repo.create_remote(remote_name, remote_url)
        return True
    except Exception as e:
        raise Exception(f"Failed to add remote {remote_name}: {str(e)}")


def git_add_commit_push(
    repo, files=None, commit_message=None, remote=None, branch="master"
):
    """Add, commit and push files to a git repository."""
    try:
        # Add files
        if files:
            for file in files:
                repo.git.add(file)
        else:
            repo.git.add(".")

        # Check if there are changes to commit
        if repo.is_dirty() or len(repo.untracked_files) > 0:
            # Commit changes
            repo.git.commit("-m", commit_message or "Update files")

        # Push if remote is specified
        if remote:
            repo.git.push(remote, branch)

        return True
    except Exception as e:
        raise Exception(f"Git operation failed: {str(e)}")


def get_git_remote_url(repo, remote_name):
    """Get the URL of a git remote.

    Args:
        repo: GitPython repository object
        remote_name: Name of the remote

    Returns:
        URL string of the remote or None if remote doesn't exist
    """
    try:
        for remote in repo.remotes:
            if remote.name == remote_name:
                return next(remote.urls, None)
        return None
    except Exception:
        return None


def get_all_remotes(repo):
    """Get all remotes from a git repository as a dictionary.

    Args:
        repo: GitPython repository object

    Returns:
        Dictionary mapping remote names to their URLs
    """
    try:
        return {remote.name: next(remote.urls, None) for remote in repo.remotes}
    except Exception:
        return {}
