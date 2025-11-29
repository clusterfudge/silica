"""Simple HTTP client for memory proxy API."""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class MemoryProxyClient:
    """Client for memory proxy HTTP API."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: int = 30,
        verify_ssl: bool = True,
    ):
        """Initialize client.

        Args:
            base_url: Memory proxy service URL
            token: Authentication token
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.verify_ssl = verify_ssl

        # Create httpx client
        self.client = httpx.Client(
            timeout=timeout,
            verify=verify_ssl,
            headers={"Authorization": f"Bearer {token}"},
        )

    def health_check(self, timeout: Optional[int] = None) -> dict:
        """Check service health.

        Args:
            timeout: Optional timeout override

        Returns:
            Health check response

        Raises:
            httpx.HTTPError: Request failed
        """
        response = self.client.get(
            f"{self.base_url}/health",
            timeout=timeout if timeout is not None else self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_manifest(self, namespace: str) -> dict:
        """Get sync manifest for namespace.

        Args:
            namespace: Namespace identifier

        Returns:
            Manifest with versions dict

        Raises:
            httpx.HTTPError: Request failed
        """
        response = self.client.get(f"{self.base_url}/sync/{namespace}")
        response.raise_for_status()
        return response.json()

    def get_file(self, namespace: str, path: str) -> tuple[bytes, str]:
        """Read file from remote.

        Args:
            namespace: Namespace identifier
            path: File path

        Returns:
            Tuple of (content, version_id)

        Raises:
            httpx.HTTPStatusError: File not found or request failed
        """
        response = self.client.get(f"{self.base_url}/blob/{namespace}/{path}")
        response.raise_for_status()

        content = response.content
        version_id = response.headers.get("X-Version-Id", "unknown")

        return content, version_id

    def put_file(
        self,
        namespace: str,
        path: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict:
        """Write file to remote.

        Args:
            namespace: Namespace identifier
            path: File path
            content: File content
            content_type: MIME type

        Returns:
            Response info with version_id, etag, is_new

        Raises:
            httpx.HTTPError: Request failed
        """
        response = self.client.put(
            f"{self.base_url}/blob/{namespace}/{path}",
            content=content,
            headers={"Content-Type": content_type},
        )
        response.raise_for_status()

        return {
            "version_id": response.headers.get("X-Version-Id", "unknown"),
            "etag": response.headers.get("ETag", ""),
            "is_new": response.status_code == 201,
        }

    def delete_file(self, namespace: str, path: str) -> dict:
        """Delete file from remote (idempotent).

        Args:
            namespace: Namespace identifier
            path: File path

        Returns:
            Response info with delete_marker_version

        Raises:
            httpx.HTTPError: Request failed (but not for 404)
        """
        response = self.client.delete(f"{self.base_url}/blob/{namespace}/{path}")
        response.raise_for_status()

        return {
            "delete_marker_version": response.headers.get(
                "X-Delete-Marker-Version-Id", "unknown"
            )
        }

    def close(self):
        """Close the client."""
        self.client.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
