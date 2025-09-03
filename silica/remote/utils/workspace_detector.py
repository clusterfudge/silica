"""Workspace detection and URL routing utilities.

This module provides functionality to detect whether a workspace is configured
for local or remote mode and route requests to the appropriate antennae URL.
"""

from pathlib import Path
from typing import Optional
import requests

from silica.remote.config.multi_workspace import (
    get_workspace_config,
    is_local_workspace,
    get_workspace_port,
)


def get_antennae_url_for_workspace(
    silica_dir: Path,
    workspace_name: Optional[str] = None,
    default_remote_url: Optional[str] = None,
) -> str:
    """Get the antennae URL for a workspace based on its configuration.

    This function determines whether a workspace is configured for local or remote
    mode and returns the appropriate URL for accessing the antennae webapp.

    Args:
        silica_dir: Path to the .silica directory
        workspace_name: Name of the workspace to get URL for.
                       If None, the default workspace will be used.
        default_remote_url: Default URL template for remote workspaces.
                           Should contain {workspace} placeholder if needed.
                           If None, will be constructed from workspace config.

    Returns:
        URL string for accessing the antennae webapp for this workspace

    Raises:
        ValueError: If workspace is local but no port is configured
        RuntimeError: If workspace is remote but cannot construct URL
    """
    # Check if this is a local workspace
    if is_local_workspace(silica_dir, workspace_name):
        # Get port for local workspace
        port = get_workspace_port(silica_dir, workspace_name)
        if port is None:
            raise ValueError(
                f"Local workspace '{workspace_name}' has no port configured"
            )

        return f"http://localhost:{port}"

    # Remote workspace - need to construct remote URL
    workspace_config = get_workspace_config(silica_dir, workspace_name)

    # If a default remote URL template is provided, use it
    if default_remote_url:
        # Replace {workspace} placeholder if present
        if "{workspace}" in default_remote_url:
            actual_workspace_name = workspace_name or workspace_config.get(
                "workspace_name", "agent"
            )
            return default_remote_url.format(workspace=actual_workspace_name)
        else:
            return default_remote_url

    # Try to construct URL from workspace configuration
    app_name = workspace_config.get("app_name")
    if app_name:
        # Remote workspace URL matches the piku app name
        return f"http://{app_name}"

    raise RuntimeError(
        f"Cannot determine remote URL for workspace '{workspace_name}'. "
        "Either configure app_name in workspace config or provide default_remote_url."
    )


def is_workspace_accessible(
    silica_dir: Path, workspace_name: Optional[str] = None, timeout: float = 0.5
) -> tuple[bool, str]:
    """Check if a workspace's antennae webapp is accessible.

    This function makes an actual HTTP request to the workspace's /status endpoint
    to determine if the antennae webapp is running and accessible.

    Args:
        silica_dir: Path to the .silica directory
        workspace_name: Name of the workspace to check.
                       If None, the default workspace will be used.
        timeout: Timeout in seconds for the HTTP request (default: 0.5)

    Returns:
        Tuple of (is_accessible, reason_or_url)
        - is_accessible: True if the workspace is accessible via HTTP
        - reason_or_url: If accessible, the URL; if not, the reason why not
    """
    try:
        url = get_antennae_url_for_workspace(silica_dir, workspace_name)

        # Make actual HTTP request to /status endpoint

        # For remote workspaces, set the host header to the app name
        headers = {}
        if not is_local_workspace(silica_dir, workspace_name):
            workspace_config = get_workspace_config(silica_dir, workspace_name)
            app_name = workspace_config.get("app_name")
            if app_name:
                headers["Host"] = app_name

        # Make request to /status endpoint with short timeout
        response = requests.get(f"{url}/status", headers=headers, timeout=timeout)

        if response.status_code == 200:
            return True, url
        else:
            return False, f"HTTP {response.status_code} from {url}/status"

    except requests.exceptions.Timeout:
        return False, f"Timeout connecting to {url}"
    except requests.exceptions.ConnectionError:
        return False, f"Connection failed to {url}"
    except requests.exceptions.RequestException as e:
        return False, f"HTTP error: {str(e)}"
    except (ValueError, RuntimeError) as e:
        return False, str(e)


def get_workspace_type_info(
    silica_dir: Path, workspace_name: Optional[str] = None
) -> dict:
    """Get detailed information about a workspace's type and configuration.

    Args:
        silica_dir: Path to the .silica directory
        workspace_name: Name of the workspace to get info for.
                       If None, the default workspace will be used.

    Returns:
        Dictionary with workspace type information:
        - name: Workspace name
        - mode: "local" or "remote"
        - port: Port number (for local workspaces only)
        - url: Antennae URL (if determinable)
        - accessible: Whether workspace appears accessible
        - error: Error message (if not accessible)
    """
    from silica.remote.config.multi_workspace import get_default_workspace

    # Get actual workspace name
    actual_name = workspace_name or get_default_workspace(silica_dir)

    # Get basic info
    mode = "local" if is_local_workspace(silica_dir, workspace_name) else "remote"
    port = get_workspace_port(silica_dir, workspace_name) if mode == "local" else None

    # Check accessibility
    accessible, url_or_reason = is_workspace_accessible(silica_dir, workspace_name)

    info = {
        "name": actual_name,
        "mode": mode,
        "accessible": accessible,
    }

    if port is not None:
        info["port"] = port

    if accessible:
        info["url"] = url_or_reason
    else:
        info["error"] = url_or_reason

    return info
