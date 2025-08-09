"""Utility functions for interacting with piku CLI."""

import os
import subprocess
from pathlib import Path
import shlex
from typing import Optional, List, Dict, Union
import git

from silica.remote.config import find_git_root, get_silica_dir, get_config_value


def get_piku_connection_for_workspace(
    workspace_name: str, git_root: Optional[Path] = None
) -> str:
    """Get the piku connection string for a specific workspace.

    This function retrieves the piku connection string associated with a workspace name
    by looking for a git remote with the same name in the agent repository.

    Args:
        workspace_name: The workspace name to look for
        git_root: Optional git root path. If None, will be detected automatically.

    Returns:
        The piku connection string (e.g., "piku", "piku@host")
    """
    if git_root is None:
        git_root = find_git_root()

    if not git_root:
        return get_config_value("piku_connection", "piku")

    # Check if we have a .silica/agent-repo directory with a matching remote
    silica_dir = get_silica_dir(git_root)
    if silica_dir:
        agent_repo_path = silica_dir / "agent-repo"
        if agent_repo_path.exists():
            try:
                agent_repo = git.Repo(agent_repo_path)
                # Look for a remote with the same name as workspace_name
                for remote in agent_repo.remotes:
                    if remote.name == workspace_name:
                        remote_url = next(remote.urls, None)
                        if remote_url:
                            # Extract host part from the remote URL (e.g., piku@host:repo -> piku@host)
                            if ":" in remote_url and not remote_url.startswith(
                                "ssh://"
                            ):
                                # Format: [user@]host:path
                                connection = remote_url.split(":", 1)[0]
                                return connection
                            elif remote_url.startswith("ssh://"):
                                # Format: ssh://[user@]host[:port]/path
                                # Remove ssh:// prefix
                                connection = remote_url[6:].split("/", 1)[0]
                                return connection
            except (git.exc.InvalidGitRepositoryError, Exception):
                pass  # Fall back to default

    # If we can't determine from agent-repo, fall back to global config
    return get_config_value("piku_connection", "piku")


def get_agent_config(
    git_root: Optional[Path] = None, workspace_name: Optional[str] = None
) -> Dict[str, str]:
    """Get the agent configuration from the .silica directory.

    Args:
        git_root: Optional git root path. If None, will be detected automatically.
        workspace_name: Optional workspace name. If None, the default workspace will be used.

    Returns:
        Dict containing the agent configuration.
    """
    if git_root is None:
        git_root = find_git_root()

    if not git_root:
        raise ValueError("Not in a git repository")

    silica_dir = get_silica_dir(git_root)

    if not silica_dir:
        raise ValueError("No silica environment found in this repository")

    # Import multi-workspace config functions
    from silica.remote.config.multi_workspace import (
        get_workspace_config,
        get_default_workspace,
    )

    # Load the project config
    if not (silica_dir / "config.yaml").exists():
        # No configuration yet, return defaults
        return {
            "workspace_name": workspace_name or "agent",
            "piku_connection": get_config_value("piku_connection", "piku"),
            "branch": "main",
        }

    # Get the workspace name if not provided
    if workspace_name is None:
        # Use the default workspace
        workspace_name = get_default_workspace(silica_dir)

    # Get the workspace-specific configuration
    workspace_config = get_workspace_config(silica_dir, workspace_name)

    # Add workspace_name to the returned config
    local_config = dict(workspace_config)
    local_config["workspace_name"] = workspace_name

    # Ensure essential keys have values
    if "piku_connection" not in local_config:
        local_config["piku_connection"] = get_piku_connection_for_workspace(
            workspace_name, git_root
        )

    # Construct app_name if needed
    if "app_name" not in local_config and git_root:
        local_config["app_name"] = f"{workspace_name}-{git_root.name}"

    return local_config


def get_workspace_name(
    git_root: Optional[Path] = None, workspace_name: Optional[str] = None
) -> str:
    """Get the workspace name for the current repository.

    Args:
        git_root: Optional git root path. If None, will be detected automatically.
        workspace_name: Optional explicit workspace name. If provided, this will be returned.
                       If None, the default workspace will be determined from config.

    Returns:
        The workspace name (e.g., "agent", "assistant", etc.)
    """
    # If workspace_name is explicitly provided, use it
    if workspace_name is not None:
        return workspace_name

    # Otherwise get from config
    if git_root is None:
        git_root = find_git_root()

    if not git_root:
        return "agent"  # Fallback default

    silica_dir = get_silica_dir(git_root)
    if not silica_dir:
        return "agent"  # Fallback default

    try:
        # Import multi-workspace config functions
        from silica.remote.config.multi_workspace import get_default_workspace

        # Get the default workspace name
        return get_default_workspace(silica_dir)
    except Exception:
        # If anything goes wrong, return the default
        return "agent"


def get_piku_connection(
    git_root: Optional[Path] = None, workspace_name: Optional[str] = None
) -> str:
    """Get the piku connection string for the current repository.

    Args:
        git_root: Optional git root path. If None, will be detected automatically.
        workspace_name: Optional explicit workspace name to use. If None, the default workspace will be used.

    Returns:
        The piku connection string (e.g., "piku", "piku@host")
    """
    try:
        if workspace_name is None:
            # Get the workspace name from configuration
            config = get_agent_config(git_root)
            workspace_name = config.get("workspace_name", "agent")
        # Get the connection string associated with this workspace
        return get_piku_connection_for_workspace(workspace_name, git_root)
    except ValueError:
        # Fall back to global config
        return get_config_value("piku_connection", "piku")


def get_app_name(
    git_root: Optional[Path] = None, workspace_name: Optional[str] = None
) -> str:
    """Get the application name for the current repository.

    Args:
        git_root: Optional git root path. If None, will be detected automatically.
        workspace_name: Optional explicit workspace name to use. If None, the default workspace will be used.

    Returns:
        The application name.
    """
    try:
        # If no explicit workspace_name provided, get it from config
        if workspace_name is None:
            config = get_agent_config(git_root)
            if "app_name" in config:
                return config.get("app_name")

            # If app_name not set directly, get workspace name from config
            workspace_name = config.get("workspace_name", "agent")
        else:
            # Check if there's a specific app_name for this workspace
            config = get_agent_config(git_root, workspace_name=workspace_name)
            if "app_name" in config:
                return config.get("app_name")

        # Construct app_name from workspace name and repo name
        if git_root is None:
            git_root = find_git_root()

        if git_root:
            return f"{workspace_name}-{git_root.name}"

    except ValueError:
        # If no config found but in a git repo, construct app name from repo name
        if git_root is None:
            git_root = find_git_root()

        if git_root:
            # Use provided workspace_name or default to "agent"
            ws_name = workspace_name or "agent"
            return f"{ws_name}-{git_root.name}"

    raise ValueError("Not in a git repository")


def run_piku_command(
    command: str,
    args: Optional[List[str]] = None,
    capture_output: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a piku command.

    Args:
        command: The piku subcommand to run (e.g., 'status', 'logs', 'config:set')
        args: Optional list of arguments for the command
        capture_output: Whether to capture the command output
        check: Whether to check the return code

    Returns:
        CompletedProcess instance with command results
    """
    cmd_parts = ["piku", command]
    if args:
        cmd_parts.extend(args)

    cmd = " ".join(shlex.quote(str(part)) for part in cmd_parts)

    return subprocess.run(
        cmd, shell=True, check=check, capture_output=capture_output, text=True
    )


def run_piku_shell(
    shell_command: str,
    remote_name: Optional[str] = None,
    cwd: Optional[Path] = None,
    capture_output: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command in the piku shell.

    Args:
        shell_command: Command to run in the piku shell
        cwd: Optional working directory for the command
        capture_output: Whether to capture the command output
        check: Whether to check the return code

    Returns:
        CompletedProcess instance with command results
    """
    # Make sure the command ends with an exit to avoid hanging
    if not shell_command.strip().endswith("exit"):
        shell_command = f"{shell_command.strip()} && exit"

    cmd = f'echo "{shell_command}" | piku shell'

    return subprocess.run(
        cmd, shell=True, check=check, capture_output=capture_output, text=True, cwd=cwd
    )


def status(app_name: Optional[str] = None) -> subprocess.CompletedProcess:
    """Check the status of an application.

    Args:
        app_name: The application name. If None, will try to detect from current repository.

    Returns:
        CompletedProcess instance with command results
    """
    if app_name is None:
        app_name = get_app_name()

    return run_piku_command("status", [app_name], capture_output=True)


def logs(
    app_name: Optional[str] = None, tail: Optional[int] = None, follow: bool = False
) -> subprocess.CompletedProcess:
    """Get logs for an application.

    Args:
        app_name: The application name. If None, will try to detect from current repository.
        tail: Number of log lines to show (None shows all logs)
        follow: Whether to follow the logs in real time

    Returns:
        CompletedProcess instance with command results
    """
    if app_name is None:
        app_name = get_app_name()

    args = [app_name]
    if tail is not None:
        args.append(str(tail))

    # For follow mode, we can't capture output
    capture_output = not follow

    return run_piku_command("logs", args, capture_output=capture_output)


def set_config(
    app_name: Optional[str] = None,
    key: str = None,
    value: str = None,
    config_dict: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """Set configuration for an application.

    Args:
        app_name: The application name. If None, will try to detect from current repository.
        key: Configuration key
        value: Configuration value
        config_dict: Dictionary of configuration keys and values (alternative to key/value pair)

    Returns:
        CompletedProcess instance with command results
    """
    if app_name is None:
        app_name = get_app_name()

    if config_dict:
        # Convert dictionary to KEY=VALUE format
        items = [f"{k}={v}" for k, v in config_dict.items()]
        return run_piku_command("config:set", [app_name] + items)
    elif key and value is not None:
        return run_piku_command("config:set", [app_name, f"{key}={value}"])
    else:
        raise ValueError("Either key/value pair or config_dict must be provided")


def get_config(
    app_name: Optional[str] = None, key: Optional[str] = None
) -> Dict[str, str]:
    """Get configuration for an application.

    Args:
        app_name: The application name. If None, will try to detect from current repository.
        key: Specific configuration key to get. If None, all configuration is returned.

    Returns:
        Dictionary of configuration values
    """
    if app_name is None:
        app_name = get_app_name()

    args = [app_name]
    if key:
        args.append(key)

    result = run_piku_command("config:get", args, capture_output=True)

    # Parse the output into a dictionary
    config = {}
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if "=" in line:
            k, v = line.split("=", 1)
            config[k] = v

    return config


def shell_command(
    command: str,
    app_name: Optional[str] = None,
    piku_connection: Optional[str] = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess:
    """Run a command in the application's directory on the piku server.

    Args:
        command: The command to run
        app_name: The application name. If None, will try to detect from current repository.
        piku_connection: The connection string for piku. If None, will try to detect from config.
        capture_output: Whether to capture the command output

    Returns:
        CompletedProcess instance with command results
    """
    if piku_connection is None:
        piku_connection = get_piku_connection()

    # Make sure the command ends with an exit to avoid hanging
    if not command.strip().endswith("exit"):
        command = f"{command.strip()} && exit"

    cmd = f'echo "{command}" | piku -r {piku_connection} shell'

    return subprocess.run(
        cmd, shell=True, check=True, capture_output=capture_output, text=True
    )


def restart(app_name: Optional[str] = None) -> subprocess.CompletedProcess:
    """Restart an application.

    Args:
        app_name: The application name. If None, will try to detect from current repository.

    Returns:
        CompletedProcess instance with command results
    """
    if app_name is None:
        app_name = get_app_name()

    return run_piku_command("restart", [app_name])


def destroy(
    app_name: Optional[str] = None, force: bool = False, terminate_tmux: bool = True
) -> subprocess.CompletedProcess:
    """Destroy an application.

    Args:
        app_name: The application name. If None, will try to detect from current repository.
        force: Whether to force removal without confirmation
        terminate_tmux: Whether to terminate tmux sessions for this application

    Returns:
        CompletedProcess instance with command results
    """
    if app_name is None:
        app_name = get_app_name()

    # Check if there's a tmux session but don't terminate it yet - this allows external callers
    # to check for sessions and get confirmation before any destructive actions
    has_tmux_session = False
    if terminate_tmux:
        try:
            # Check if there's a tmux session for this app
            check_cmd = (
                f"tmux has-session -t {app_name} 2>/dev/null || echo 'no_session'"
            )
            check_result = shell_command(
                check_cmd, app_name=app_name, capture_output=True
            )
            has_tmux_session = "no_session" not in check_result.stdout
        except Exception:
            # Ignore errors when checking for tmux sessions
            pass

    # Prepare arguments for piku destroy
    args = [app_name]
    if force:
        args.append("--force")

    # Run the destroy command first
    result = run_piku_command("destroy", args)

    # Now terminate the tmux session if it exists
    if terminate_tmux and has_tmux_session:
        try:
            # Session should still exist, kill it
            kill_cmd = f"tmux kill-session -t {app_name}"
            shell_command(kill_cmd, app_name=app_name)
        except Exception:
            # Ignore errors when trying to terminate tmux sessions
            pass

    return result


def deploy(git_root: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Deploy the agent repository to piku.

    This function finds the agent repository in the .silica directory and pushes it to piku.

    Args:
        git_root: Optional git root path. If None, will be detected automatically.

    Returns:
        CompletedProcess instance with command results
    """
    if git_root is None:
        git_root = find_git_root()

    if not git_root:
        raise ValueError("Not in a git repository")

    # Get agent configuration
    config = get_agent_config(git_root)
    workspace_name = config.get("workspace_name", "agent")
    branch = config.get("branch", "main")

    # Get the agent repository path
    silica_dir = get_silica_dir(git_root)
    repo_path = silica_dir / "agent-repo"

    # Push to piku
    import git

    repo = git.Repo(repo_path)

    # Add all changes
    repo.git.add(".")

    # Commit if there are changes
    if repo.is_dirty() or len(repo.untracked_files) > 0:
        repo.git.commit("-m", "Update agent environment")

    # Push to the git remote with the same name as workspace_name
    return subprocess.run(
        f"cd {repo_path} && git push {workspace_name} {branch}",
        shell=True,
        check=True,
        text=True,
    )


def run_hdev_command(
    command: str,
    args: Optional[List[str]] = None,
    app_name: Optional[str] = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess:
    """Run an hdev command on the piku server.

    Args:
        command: The hdev subcommand to run
        args: Optional arguments for the command
        app_name: The application name. If None, will try to detect from current repository.
        capture_output: Whether to capture the command output

    Returns:
        CompletedProcess instance with command results
    """
    if app_name is None:
        app_name = get_app_name()

    cmd_parts = ["hdev", command]
    if args:
        cmd_parts.extend(args)

    cmd = " ".join(shlex.quote(str(part)) for part in cmd_parts)

    return shell_command(cmd, app_name, capture_output=capture_output)


def list_sessions(app_name: Optional[str] = None) -> List[Dict[str, str]]:
    """List active sessions for an application.

    Args:
        app_name: The application name. If None, will try to detect from current repository.

    Returns:
        List of session information dictionaries
    """
    if app_name is None:
        app_name = get_app_name()

    result = run_hdev_command("sessions", [], app_name, capture_output=True)

    # Parse the output into a list of dictionaries
    sessions = []
    lines = result.stdout.strip().split("\n")

    # Skip if no sessions found
    if "No sessions found" in result.stdout:
        return []

    # Skip the header line if there are multiple lines
    if len(lines) > 1:
        for line in lines[1:]:  # Skip header
            parts = line.split()
            if len(parts) >= 3:
                session_id = parts[0]
                started = parts[1]
                workdir = " ".join(parts[2:])
                sessions.append(
                    {"id": session_id, "started": started, "workdir": workdir}
                )

    return sessions


def sync_local_to_remote(
    workspace_name: str,
    git_root: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    """Sync the local repository to the remote code directory.

    Args:
        workspace_name: The workspace name to sync to (required)
        git_root: Optional git root path. If None, will be detected automatically.

    Returns:
        CompletedProcess instance with command results
    """
    if git_root is None:
        git_root = find_git_root()

    if not git_root:
        raise ValueError("Not in a git repository")

    # Get application name
    app_name = get_app_name(git_root)

    # Get connection for the specified workspace
    piku_connection = get_piku_connection_for_workspace(workspace_name, git_root)

    # Create an rsync command to sync the local repo to the remote's code directory
    # Exclude the .silica and .git directories
    rsync_cmd = (
        f"rsync -av --delete --exclude='.silica' --exclude='.git' "
        f"{git_root}/ "
        f"/home/piku/app_dirs/{app_name}/code/"
    )

    return shell_command(rsync_cmd, piku_connection=piku_connection)


def run_in_silica_dir(
    command: str,
    use_shell: bool = True,
    capture_output: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command within the .silica directory context.

    This function:
    1. Finds the local .silica directory
    2. Changes the working directory to it
    3. Runs the specified command
    4. Returns to the original working directory

    Args:
        command: The command to run (can be a piku command or any other command)
        use_shell: Whether to run the command through the shell
        capture_output: Whether to capture the command's output
        check: Whether to check the return code and raise an exception on failure

    Returns:
        CompletedProcess instance with command results

    Raises:
        ValueError: If not in a git repository or .silica directory doesn't exist
        subprocess.CalledProcessError: If check=True and the command returns non-zero
    """
    # Save the current working directory
    original_dir = Path.cwd()

    try:
        # Find the git root and .silica directory
        git_root = find_git_root()
        if not git_root:
            raise ValueError("Not in a git repository")

        silica_dir = get_silica_dir(git_root)
        if not silica_dir or not silica_dir.exists():
            raise ValueError("No .silica directory found in this repository")

        # Change to the .silica directory first
        os.chdir(silica_dir)

        # Then change to the agent-repo subdirectory if it exists
        agent_repo_dir = silica_dir / "agent-repo"
        if agent_repo_dir.exists():
            os.chdir(agent_repo_dir)

        # Directory change is already handled above

        # Run the command
        result = subprocess.run(
            command,
            shell=use_shell,
            capture_output=capture_output,
            check=check,
            text=True,
        )

        return result

    finally:
        # Always return to the original directory
        os.chdir(original_dir)


def run_piku_in_silica(
    piku_command: str,
    workspace_name: str,
    use_shell_pipe: bool = False,
    capture_output: bool = False,
    check: bool = True,
    git_root: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    """Run a Piku command within the .silica directory context.

    This is a specialized version of run_in_silica_dir that specifically handles
    Piku commands, with the option to pipe into the Piku shell.

    Args:
        piku_command: The Piku command to run (e.g., 'status', 'logs')
        workspace_name: Required workspace name for this specific agent/workspace.
        use_shell_pipe: Whether to pipe the command into 'piku shell' instead of running directly
        capture_output: Whether to capture the command's output
        check: Whether to check the return code and raise an exception on failure
        git_root: Optional git root path. If None, will be detected automatically.

    Returns:
        CompletedProcess instance with command results

    Raises:
        ValueError: If not in a git repository or .silica directory doesn't exist
        subprocess.CalledProcessError: If check=True and the command returns non-zero
    """
    # Get git root if not provided
    if git_root is None:
        git_root = find_git_root()
        if not git_root:
            raise ValueError("Not in a git repository")

    # Construct the piku command with connection string
    piku_base = f"piku -r {workspace_name}"

    if use_shell_pipe:
        # Ensure the command ends with exit to avoid hanging
        if not piku_command.strip().endswith("exit"):
            piku_command = f"{piku_command.strip()} && exit"
        command = f'echo "{piku_command}" | {piku_base} shell'
    else:
        # Direct piku command
        command = f"{piku_base} {piku_command}"

    return run_in_silica_dir(
        command, use_shell=True, capture_output=capture_output, check=check
    )


def clear_uv_cache(
    workspace_name: str,
    git_root: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    """Clear UV cache on the remote workspace.

    Args:
        workspace_name: Required workspace name
        git_root: Optional git root path. If None, will be detected automatically

    Returns:
        CompletedProcess instance with command results

    Raises:
        subprocess.CalledProcessError: If the cache clearing fails
    """
    # Clear UV cache using uv cache clean command
    cache_cmd = "uv cache clean"

    return run_piku_in_silica(
        cache_cmd,
        workspace_name=workspace_name,
        use_shell_pipe=True,
        capture_output=True,
        check=False,  # Don't fail if cache doesn't exist
        git_root=git_root,
    )


def sync_dependencies_with_cache_clear(
    workspace_name: str,
    clear_cache: bool = True,
    git_root: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    """Sync UV dependencies on remote workspace, optionally clearing cache first.

    Args:
        workspace_name: Required workspace name
        clear_cache: Whether to clear UV cache before syncing
        git_root: Optional git root path. If None, will be detected automatically

    Returns:
        CompletedProcess instance with command results

    Raises:
        subprocess.CalledProcessError: If the sync fails
    """
    if clear_cache:
        # Clear cache first (don't fail if it doesn't work)
        try:
            clear_uv_cache(workspace_name, git_root)
        except subprocess.CalledProcessError:
            # Ignore cache clearing failures
            pass

    # Sync dependencies with upgrade flag to ensure latest versions
    sync_cmd = "uv sync --upgrade"

    return run_piku_in_silica(
        sync_cmd,
        workspace_name=workspace_name,
        use_shell_pipe=True,
        capture_output=True,
        check=True,
        git_root=git_root,
    )


def upload_to_workspace(
    local_path: Union[str, Path],
    workspace_name: str,
    remote_path: Optional[Union[str, Path]] = None,
    app_name: Optional[str] = None,
    git_root: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    """Upload a local file or directory to the remote workspace.

    Args:
        local_path: Path to the local file or directory to upload
        workspace_name: Required workspace name
        remote_path: Destination path on the remote workspace relative to the app folder
                    If None, the file will be uploaded with the same name
        app_name: Optional application name. If None, will try to detect from current repository
        git_root: Optional git root path. If None, will be detected automatically

    Returns:
        CompletedProcess instance with command results

    Raises:
        ValueError: If the local path doesn't exist or remote information can't be determined
        subprocess.CalledProcessError: If the upload fails
    """
    local_path = Path(local_path).resolve()

    if not local_path.exists():
        raise ValueError(f"Local path does not exist: {local_path}")

    # Get app_name if not provided
    if app_name is None:
        app_name = get_app_name(git_root)

    # If remote_path is not provided, use the local filename
    if remote_path is None:
        remote_path = local_path.name

    # Format for scp command
    # Get the connection string for this workspace
    server = get_piku_connection_for_workspace(workspace_name, git_root)
    remote_dest = f"{server}:~/.piku/apps/{app_name}/{remote_path}"

    # Run scp command to upload
    return subprocess.run(
        ["scp", "-r", str(local_path), remote_dest],
        check=True,
        capture_output=True,
        text=True,
    )
