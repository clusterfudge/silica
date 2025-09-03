"""Workspace detection and URL routing utilities.

This module provides functionality to get workspace URLs and check accessibility.
All workspace configuration is stored at creation time - we only read it here.

TODO: The HTTP client functionality in this module should be moved to an
`antennae.client` module that handles constructing HTTP requests correctly
given a workspace config.
"""

from pathlib import Path
from typing import Optional
import requests

from silica.remote.config.multi_workspace import get_workspace_config


def get_workspace_url(silica_dir: Path, workspace_name: Optional[str] = None) -> str:
    """Get the URL for a workspace from its configuration.

    Args:
        silica_dir: Path to the .silica directory
        workspace_name: Name of the workspace to get URL for.
                       If None, the default workspace will be used.

    Returns:
        URL string for accessing the antennae webapp for this workspace

    Raises:
        ValueError: If workspace has no URL configured
    """
    workspace_config = get_workspace_config(silica_dir, workspace_name)
    url = workspace_config.get("url")

    if not url:
        raise ValueError(f"Workspace '{workspace_name}' has no URL configured")

    return url


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
        url = get_workspace_url(silica_dir, workspace_name)
        workspace_config = get_workspace_config(silica_dir, workspace_name)
        app_name = workspace_config.get("app_name", "unknown")

        # Always set host header to app_name for proper routing and observability
        headers = {"Host": app_name}

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
