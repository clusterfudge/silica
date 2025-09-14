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


def is_github_repo(repo_url):
    """Check if a repository URL is a GitHub repository.

    Args:
        repo_url: Repository URL to check

    Returns:
        True if this is a GitHub repository, False otherwise
    """
    return "github.com" in repo_url


def extract_github_repo_path(repo_url):
    """Extract the owner/repo path from a GitHub URL.

    Args:
        repo_url: GitHub repository URL

    Returns:
        Repository path in format "owner/repo" or empty string if not GitHub
    """
    if not is_github_repo(repo_url):
        return ""

    # Format could be https://github.com/user/repo.git or git@github.com:user/repo.git
    if repo_url.startswith("https://"):
        return repo_url.replace("https://github.com/", "").replace(".git", "")
    else:
        return repo_url.split("github.com:")[1].replace(".git", "")


def convert_github_ssh_to_https(repo_url):
    """Convert GitHub SSH URL to HTTPS URL.

    Args:
        repo_url: Repository URL (SSH or HTTPS)

    Returns:
        HTTPS URL for GitHub repositories, original URL for others
    """
    if not is_github_repo(repo_url):
        return repo_url

    if repo_url.startswith("git@github.com:"):
        # Convert git@github.com:user/repo.git to https://github.com/user/repo.git
        repo_path = repo_url.replace("git@github.com:", "")
        return f"https://github.com/{repo_path}"

    # Already HTTPS or other format
    return repo_url


def check_gh_cli_available():
    """Check if GitHub CLI (gh) is available.

    Returns:
        True if gh CLI is available, False otherwise
    """
    try:
        subprocess.run(
            ["gh", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def clone_repository(repo_url, destination_path, branch="main", use_https=True):
    """Clone a repository using the most appropriate method.

    For GitHub repositories, uses GitHub CLI (gh) with HTTPS scheme if available.
    Falls back to regular git clone as needed.

    Args:
        repo_url: Repository URL to clone
        destination_path: Path where to clone the repository
        branch: Branch to clone (default: main)
        use_https: Whether to prefer HTTPS for GitHub repositories (default: True)

    Returns:
        True if clone succeeded, False otherwise
    """
    import logging
    import shutil

    logger = logging.getLogger(__name__)

    try:
        destination_path = Path(destination_path)

        # Remove destination if it already exists
        if destination_path.exists():
            shutil.rmtree(destination_path)

        destination_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert SSH URLs to HTTPS for GitHub repositories when use_https=True
        clone_url = repo_url
        if is_github_repo(repo_url) and use_https:
            clone_url = convert_github_ssh_to_https(repo_url)
            if clone_url != repo_url:
                logger.info(f"Converted SSH URL to HTTPS: {repo_url} → {clone_url}")

        # For GitHub repositories, try GitHub CLI first if available
        if is_github_repo(clone_url) and check_gh_cli_available():
            repo_path = extract_github_repo_path(clone_url)
            if repo_path:
                logger.info(f"Cloning GitHub repository {repo_path} using gh CLI")

                cmd = ["gh", "repo", "clone", repo_path, str(destination_path)]
                if branch != "main":
                    # Use git flags after -- separator for branch specification
                    cmd.extend(["--", "--branch", branch])

                result = subprocess.run(
                    cmd, capture_output=True, text=True, check=False
                )

                if result.returncode == 0:
                    logger.info("Successfully cloned using gh CLI")
                    return True
                else:
                    logger.warning(f"gh CLI clone failed: {result.stderr}")
                    # Fall through to regular git clone

        # Fall back to regular git clone with the converted URL
        logger.info(f"Cloning repository {clone_url} using git")

        # Use git.Repo.clone_from with the HTTPS URL for GitHub repos
        git.Repo.clone_from(clone_url, destination_path, branch=branch)
        logger.info("Successfully cloned using git")
        return True

    except Exception as e:
        logger.error(f"Repository clone failed: {e}")
        return False
