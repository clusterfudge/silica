"""Workspace detection and URL routing utilities.

This module provides functionality to detect whether a workspace is configured
for local or remote mode and route requests to the appropriate antennae URL.
"""

from pathlib import Path
from typing import Optional

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
        # If we have an app_name, assume it's deployed and accessible
        # This is a placeholder - in a real deployment you'd have a domain pattern
        # For now, just return a placeholder that indicates remote deployment
        return f"https://{app_name}.example.com"  # Placeholder - should be configurable

    raise RuntimeError(
        f"Cannot determine remote URL for workspace '{workspace_name}'. "
        "Either configure app_name in workspace config or provide default_remote_url."
    )


def is_workspace_accessible(
    silica_dir: Path, workspace_name: Optional[str] = None
) -> tuple[bool, str]:
    """Check if a workspace's antennae webapp is accessible.

    This function attempts to determine if the antennae webapp for a workspace
    is accessible by checking the configuration and (for local workspaces)
    whether the expected port is available.

    Args:
        silica_dir: Path to the .silica directory
        workspace_name: Name of the workspace to check.
                       If None, the default workspace will be used.

    Returns:
        Tuple of (is_accessible, reason_or_url)
        - is_accessible: True if the workspace appears to be accessible
        - reason_or_url: If accessible, the URL; if not, the reason why not
    """
    try:
        url = get_antennae_url_for_workspace(silica_dir, workspace_name)

        if is_local_workspace(silica_dir, workspace_name):
            # For local workspaces, we can only check if config is valid
            # Actual accessibility would require a network check
            return True, url
        else:
            # For remote workspaces, assume accessible if we can construct URL
            return True, url

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
