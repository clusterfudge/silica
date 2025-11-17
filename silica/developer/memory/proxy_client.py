"""HTTP client for Memory Proxy service.

This module provides a client for interacting with the Memory Proxy service,
which provides remote storage and synchronization for persona files including
memory entries, history files, and persona definitions.
"""

import logging
from datetime import datetime
from typing import Tuple

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class FileMetadata(BaseModel):
    """Metadata for a file in the memory proxy."""

    md5: str
    last_modified: datetime
    size: int
    version: int
    is_deleted: bool = False


class SyncIndexResponse(BaseModel):
    """Response from the sync index endpoint."""

    files: dict[str, FileMetadata]
    index_last_modified: datetime
    index_version: int


class MemoryProxyError(Exception):
    """Base exception for memory proxy errors."""


class ConnectionError(MemoryProxyError):
    """Failed to connect to memory proxy service."""


class AuthenticationError(MemoryProxyError):
    """Authentication failed."""


class VersionConflictError(MemoryProxyError):
    """Version conflict detected (412 Precondition Failed)."""

    def __init__(
        self, message: str, current_version: int | None, provided_version: int
    ):
        super().__init__(message)
        self.current_version = current_version
        self.provided_version = provided_version


class NotFoundError(MemoryProxyError):
    """File not found (404)."""


class MemoryProxyClient:
    """HTTP client for Memory Proxy service.

    This client handles all communication with the memory proxy service,
    including reading, writing, and deleting blobs, as well as retrieving
    sync indices for namespaces.

    The client uses conditional writes (If-Match-Version header) to ensure
    consistency and detect conflicts.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        """Initialize the memory proxy client.

        Args:
            base_url: Base URL of the memory proxy service
            token: Authentication token
            timeout: Request timeout in seconds (default: 30)
            max_retries: Maximum number of retries for failed requests (default: 3)
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries

        # Create httpx client with retries
        transport = httpx.HTTPTransport(retries=max_retries)
        self.client = httpx.Client(
            transport=transport,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close the client."""
        self.close()

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def health_check(self) -> bool:
        """Check if the memory proxy service is accessible.

        Returns:
            True if service is healthy, False otherwise
        """
        try:
            response = self.client.get(f"{self.base_url}/health")
            if response.status_code == 200:
                data = response.json()
                return data.get("status") == "ok"
            return False
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def read_blob(
        self, namespace: str, path: str
    ) -> Tuple[bytes, str, datetime, str, int]:
        """Read a blob from the memory proxy.

        Args:
            namespace: Namespace (persona name)
            path: File path within namespace

        Returns:
            Tuple of (content, md5, last_modified, content_type, version)

        Raises:
            NotFoundError: If file doesn't exist
            ConnectionError: If request fails
            AuthenticationError: If authentication fails
        """
        url = f"{self.base_url}/blob/{namespace}/{path}"

        try:
            response = self.client.get(url)

            if response.status_code == 200:
                content = response.content
                md5 = response.headers.get("ETag", "").strip('"')
                last_modified_str = response.headers.get("Last-Modified", "")
                last_modified = datetime.strptime(
                    last_modified_str, "%a, %d %b %Y %H:%M:%S %Z"
                )
                content_type = response.headers.get("Content-Type", "")
                version = int(response.headers.get("X-Version", "0"))

                logger.debug(
                    f"Read blob: {namespace}/{path} (version={version}, size={len(content)})"
                )
                return content, md5, last_modified, content_type, version

            elif response.status_code == 404:
                raise NotFoundError(f"File not found: {namespace}/{path}")

            elif response.status_code == 401:
                raise AuthenticationError("Invalid authentication token")

            else:
                raise MemoryProxyError(
                    f"Failed to read blob: {response.status_code} {response.text}"
                )

        except httpx.RequestError as e:
            logger.error(f"Request failed: {e}")
            raise ConnectionError(f"Failed to connect to memory proxy: {e}") from e

    def write_blob(
        self,
        namespace: str,
        path: str,
        content: bytes,
        expected_version: int,
        content_type: str = "application/octet-stream",
        content_md5: str | None = None,
    ) -> Tuple[bool, str, int]:
        """Write a blob to the memory proxy with conditional write.

        Args:
            namespace: Namespace (persona name)
            path: File path within namespace
            content: File content as bytes
            expected_version: Expected version for conditional write
                            - 0 means file must not exist (create new)
                            - >0 means file must have this version (update)
            content_type: MIME type of content (default: application/octet-stream)
            content_md5: Optional MD5 hash for validation

        Returns:
            Tuple of (is_new, md5, version)

        Raises:
            VersionConflictError: If version doesn't match (412)
            ConnectionError: If request fails
            AuthenticationError: If authentication fails
        """
        url = f"{self.base_url}/blob/{namespace}/{path}"

        headers = {
            "If-Match-Version": str(expected_version),
            "Content-Type": content_type,
        }

        if content_md5:
            headers["Content-MD5"] = content_md5

        try:
            response = self.client.put(url, content=content, headers=headers)

            if response.status_code in (200, 201):
                is_new = response.status_code == 201
                md5 = response.headers.get("ETag", "").strip('"')
                version = int(response.headers.get("X-Version", "0"))

                logger.info(
                    f"{'Created' if is_new else 'Updated'} blob: {namespace}/{path} "
                    f"(version={version}, size={len(content)})"
                )
                return is_new, md5, version

            elif response.status_code == 412:
                # Version conflict
                error_data = response.json()
                context = error_data.get("context", {})
                current_version_str = context.get("current_version", "unknown")
                current_version = (
                    int(current_version_str) if current_version_str.isdigit() else None
                )

                raise VersionConflictError(
                    error_data.get("detail", "Version conflict"),
                    current_version=current_version,
                    provided_version=expected_version,
                )

            elif response.status_code == 401:
                raise AuthenticationError("Invalid authentication token")

            else:
                raise MemoryProxyError(
                    f"Failed to write blob: {response.status_code} {response.text}"
                )

        except httpx.RequestError as e:
            logger.error(f"Request failed: {e}")
            raise ConnectionError(f"Failed to connect to memory proxy: {e}") from e

    def delete_blob(
        self, namespace: str, path: str, expected_version: int | None = None
    ) -> None:
        """Delete a blob from the memory proxy (creates tombstone).

        Args:
            namespace: Namespace (persona name)
            path: File path within namespace
            expected_version: Optional expected version for conditional delete

        Raises:
            NotFoundError: If file doesn't exist
            VersionConflictError: If version doesn't match (412)
            ConnectionError: If request fails
            AuthenticationError: If authentication fails
        """
        url = f"{self.base_url}/blob/{namespace}/{path}"

        headers = {}
        if expected_version is not None:
            headers["If-Match-Version"] = str(expected_version)

        try:
            response = self.client.delete(url, headers=headers)

            if response.status_code == 204:
                logger.info(f"Deleted blob: {namespace}/{path}")
                return

            elif response.status_code == 404:
                raise NotFoundError(f"File not found: {namespace}/{path}")

            elif response.status_code == 412:
                # Version conflict
                error_data = response.json()
                context = error_data.get("context", {})
                current_version_str = context.get("current_version", "unknown")
                current_version = (
                    int(current_version_str) if current_version_str.isdigit() else None
                )

                raise VersionConflictError(
                    error_data.get("detail", "Version conflict"),
                    current_version=current_version,
                    provided_version=expected_version or 0,
                )

            elif response.status_code == 401:
                raise AuthenticationError("Invalid authentication token")

            else:
                raise MemoryProxyError(
                    f"Failed to delete blob: {response.status_code} {response.text}"
                )

        except httpx.RequestError as e:
            logger.error(f"Request failed: {e}")
            raise ConnectionError(f"Failed to connect to memory proxy: {e}") from e

    def get_sync_index(self, namespace: str) -> SyncIndexResponse:
        """Get the sync index for a namespace.

        The sync index contains metadata for all files in the namespace,
        which clients use to determine which files need syncing.

        Args:
            namespace: Namespace (persona name)

        Returns:
            SyncIndexResponse with file metadata (empty if namespace doesn't exist yet)

        Raises:
            ConnectionError: If request fails
            AuthenticationError: If authentication fails
        """
        url = f"{self.base_url}/sync/{namespace}"

        try:
            response = self.client.get(url)

            if response.status_code == 200:
                data = response.json()
                logger.debug(
                    f"Retrieved sync index for {namespace}: {len(data.get('files', {}))} files"
                )
                return SyncIndexResponse(**data)

            elif response.status_code == 404:
                # Namespace doesn't exist yet on remote - return empty index
                # This is expected for first-time sync
                logger.debug(
                    f"Namespace {namespace} not found on remote, using empty index"
                )
                return SyncIndexResponse(files={}, last_updated=None)

            elif response.status_code == 401:
                raise AuthenticationError("Invalid authentication token")

            else:
                raise MemoryProxyError(
                    f"Failed to get sync index: {response.status_code} {response.text}"
                )

        except httpx.RequestError as e:
            logger.error(f"Request failed: {e}")
            raise ConnectionError(f"Failed to connect to memory proxy: {e}") from e
