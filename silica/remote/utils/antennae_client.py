"""HTTP client for communicating with antennae webapp endpoints.

This module provides utilities for making HTTP requests to antennae webapp endpoints,
handling workspace URL detection and routing based on workspace configuration.
"""

from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import requests
from requests.exceptions import RequestException

from silica.remote.utils.workspace_detector import get_workspace_url
from silica.remote.config.multi_workspace import get_workspace_config


def get_antennae_client(
    silica_dir: Path, workspace_name: Optional[str] = None, timeout: float = 30.0
):
    """Get an HTTP client configured for a specific workspace.

    Args:
        silica_dir: Path to the .silica directory
        workspace_name: Name of the workspace to get client for
        timeout: Default timeout for HTTP requests

    Returns:
        AntennaeClient instance configured for the workspace
    """
    return AntennaeClient(silica_dir, workspace_name, timeout)


class AntennaeClient:
    """HTTP client for communicating with antennae webapp endpoints."""

    def __init__(
        self,
        silica_dir: Path,
        workspace_name: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """Initialize client for a specific workspace.

        Args:
            silica_dir: Path to the .silica directory
            workspace_name: Name of the workspace to communicate with
            timeout: Default timeout for HTTP requests
        """
        self.silica_dir = silica_dir
        self.workspace_name = workspace_name
        self.timeout = timeout

        # Get workspace configuration
        self.workspace_config = get_workspace_config(silica_dir, workspace_name)

        # Get base URL for this workspace
        self.base_url = get_workspace_url(silica_dir, workspace_name)

        # Set up headers with proper Host header for routing
        app_name = self.workspace_config.get("app_name", workspace_name or "agent")
        self.headers = {"Host": app_name, "Content-Type": "application/json"}

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Make HTTP request to antennae webapp.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (without leading slash)
            data: JSON data to send with request
            timeout: Request timeout (uses default if None)

        Returns:
            Tuple of (success, response_data)
        """
        url = f"{self.base_url}/{endpoint}"
        request_timeout = timeout or self.timeout

        try:
            if method.upper() == "GET":
                response = requests.get(
                    url, headers=self.headers, timeout=request_timeout
                )
            elif method.upper() == "POST":
                response = requests.post(
                    url, headers=self.headers, json=data, timeout=request_timeout
                )
            else:
                return False, {"error": f"Unsupported HTTP method: {method}"}

            # Parse response
            try:
                response_data = response.json()
            except ValueError:
                response_data = {"raw_response": response.text}

            # Check if request was successful
            if response.status_code >= 200 and response.status_code < 300:
                return True, response_data
            else:
                return False, {
                    "error": f"HTTP {response.status_code}",
                    "detail": response_data.get("detail", response.text),
                }

        except requests.exceptions.Timeout:
            return False, {"error": f"Timeout connecting to {url}"}
        except requests.exceptions.ConnectionError:
            return False, {"error": f"Connection failed to {url}"}
        except RequestException as e:
            return False, {"error": f"HTTP error: {str(e)}"}
        except Exception as e:
            return False, {"error": f"Unexpected error: {str(e)}"}

    def initialize(
        self, repo_url: str, branch: str = "main"
    ) -> Tuple[bool, Dict[str, Any]]:
        """Initialize workspace via POST /initialize endpoint.

        Args:
            repo_url: URL of repository to clone
            branch: Git branch to checkout

        Returns:
            Tuple of (success, response_data)
        """
        data = {"repo_url": repo_url, "branch": branch}
        return self._make_request("POST", "initialize", data)

    def tell(self, message: str) -> Tuple[bool, Dict[str, Any]]:
        """Send message to agent via POST /tell endpoint.

        Args:
            message: Message to send to agent

        Returns:
            Tuple of (success, response_data)
        """
        data = {"message": message}
        return self._make_request("POST", "tell", data)

    def get_status(self) -> Tuple[bool, Dict[str, Any]]:
        """Get workspace status via GET /status endpoint.

        Returns:
            Tuple of (success, response_data)
        """
        return self._make_request("GET", "status")

    def get_connection_info(self) -> Tuple[bool, Dict[str, Any]]:
        """Get connection info via GET /connect endpoint.

        Returns:
            Tuple of (success, response_data)
        """
        return self._make_request("GET", "connect")

    def destroy(self) -> Tuple[bool, Dict[str, Any]]:
        """Destroy workspace via POST /destroy endpoint.

        Returns:
            Tuple of (success, response_data)
        """
        return self._make_request("POST", "destroy")

    def health_check(self) -> Tuple[bool, Dict[str, Any]]:
        """Check if antennae webapp is accessible.

        Returns:
            Tuple of (success, response_data)
        """
        return self._make_request("GET", "health", timeout=5.0)
