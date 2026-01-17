"""HTTP client for communicating with antennae webapp endpoints.

This module provides utilities for making HTTP requests to antennae webapp endpoints,
handling workspace URL detection and routing based on workspace configuration.
"""

from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import requests
import time
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
        retries: int = 0,
        retry_delay: float = 1.0,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Make HTTP request to antennae webapp.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (without leading slash)
            data: JSON data to send with request
            timeout: Request timeout (uses default if None)
            retries: Number of retries on failure (default: 0)
            retry_delay: Delay between retries in seconds (default: 1.0)

        Returns:
            Tuple of (success, response_data)
        """
        url = f"{self.base_url}/{endpoint}"
        request_timeout = timeout or self.timeout

        for attempt in range(retries + 1):
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
                    # Check if this is a retryable error
                    if attempt < retries and self._is_retryable_error(
                        response.status_code
                    ):
                        time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                        continue

                    return False, {
                        "error": f"HTTP {response.status_code}",
                        "detail": response_data.get("detail", response.text),
                    }

            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as e:
                if attempt < retries:
                    time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                    continue

                error_type = (
                    "Timeout"
                    if isinstance(e, requests.exceptions.Timeout)
                    else "Connection failed"
                )
                return False, {"error": f"{error_type} connecting to {url}"}
            except RequestException as e:
                if attempt < retries:
                    time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                    continue
                return False, {"error": f"HTTP error: {str(e)}"}
            except Exception as e:
                return False, {"error": f"Unexpected error: {str(e)}"}

    def _is_retryable_error(self, status_code: int) -> bool:
        """Check if HTTP status code indicates a retryable error."""
        # Retry on server errors, service unavailable, and not found (during app startup)
        # 404 is included because piku apps may return 404 while starting up
        return status_code in [404, 500, 502, 503, 504]

    def initialize(
        self, repo_url: str, branch: str = "main", retries: int = 5
    ) -> Tuple[bool, Dict[str, Any]]:
        """Initialize workspace via POST /initialize endpoint.

        Args:
            repo_url: URL of repository to clone
            branch: Git branch to checkout
            retries: Number of retries for server startup (default: 5)

        Returns:
            Tuple of (success, response_data)
        """
        data = {"repo_url": repo_url, "branch": branch}
        return self._make_request(
            "POST", "initialize", data, retries=retries, retry_delay=2.0
        )

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

    def get_capabilities(self) -> Tuple[bool, Dict[str, Any]]:
        """Get server capabilities for feature detection.

        Returns:
            Tuple of (success, response_data with 'capabilities' list)
        """
        return self._make_request("GET", "capabilities", timeout=5.0)

    def supports_capability(self, capability: str) -> Tuple[bool, str]:
        """Check if server supports a specific capability.

        Args:
            capability: The capability to check (e.g., "execute-plan")

        Returns:
            Tuple of (supported, error_message)
            If supported, error_message is empty.
            If not supported, error_message explains why.
        """
        success, response = self.get_capabilities()

        if not success:
            # Older servers might not have /capabilities endpoint
            error = response.get("error", "Unknown error")
            if "404" in error or "Not found" in str(error).lower():
                return False, (
                    "Remote server does not support capability detection. "
                    "Please upgrade the remote antennae server to use this feature."
                )
            return False, f"Could not check server capabilities: {error}"

        capabilities = response.get("capabilities", [])
        version = response.get("version", "unknown")

        if capability in capabilities:
            return True, ""
        else:
            return False, (
                f"Remote server (version {version}) does not support '{capability}'. "
                f"Supported capabilities: {', '.join(capabilities) or 'none'}. "
                "Please upgrade the remote antennae server."
            )

    def execute_plan(
        self,
        repo_url: str,
        branch: str,
        plan_id: str,
        plan_title: str = "",
        retries: int = 5,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Execute a plan in the workspace.

        This initializes the workspace with the specified branch and
        sends the agent instructions to execute the plan.

        Args:
            repo_url: URL of repository containing the plan
            branch: Git branch to checkout (should contain the plan)
            plan_id: ID of the plan to execute
            plan_title: Title of the plan (for display)
            retries: Number of retries for server startup

        Returns:
            Tuple of (success, response_data)
        """
        data = {
            "repo_url": repo_url,
            "branch": branch,
            "plan_id": plan_id,
            "plan_title": plan_title,
        }
        return self._make_request(
            "POST", "execute-plan", data, retries=retries, retry_delay=2.0
        )

    def get_plan_status(
        self,
        plan_id: str,
        retries: int = 2,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Get status of a plan being executed in the workspace.

        Args:
            plan_id: ID of the plan to query
            retries: Number of retries for transient failures

        Returns:
            Tuple of (success, response_data) where response_data contains:
            - plan_id: str
            - plan_title: str
            - plan_slug: str
            - status: str ("unknown", "draft", "in_progress", "completed", "abandoned")
            - current_task: str | None
            - tasks_completed: int
            - tasks_verified: int
            - tasks_total: int
            - elapsed_seconds: float | None
            - agent_status: str ("idle", "working", "error", "unknown")
        """
        return self._make_request(
            "GET", f"plan-status/{plan_id}", retries=retries, retry_delay=1.0
        )
