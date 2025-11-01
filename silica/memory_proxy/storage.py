"""S3 storage operations for Memory Proxy service."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Tuple

import boto3
from botocore.exceptions import ClientError

from .config import Settings
from .models import FileMetadata, SyncIndexResponse

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Base exception for storage operations."""


class FileNotFoundError(StorageError):
    """File does not exist in storage."""


class PreconditionFailedError(StorageError):
    """Conditional operation failed (version mismatch)."""

    def __init__(self, message: str, current_version: str, provided_version: str):
        super().__init__(message)
        self.current_version = current_version
        self.provided_version = provided_version
        # Backwards compatibility aliases
        self.current_md5 = current_version
        self.provided_md5 = provided_version


class S3Storage:
    """Handles all S3 operations for the Memory Proxy service."""

    SENTINEL_NEW_FILE = "new"

    def __init__(self, settings: Settings = None):
        """Initialize S3 client."""
        if settings is None:
            settings = Settings()

        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
            endpoint_url=settings.s3_endpoint_url,
        )
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.rstrip("/")

    def _make_key(self, namespace: str, path: str) -> str:
        """Convert a namespace and file path to an S3 key with prefix."""
        # Remove leading slashes if present
        namespace = namespace.lstrip("/")
        path = path.lstrip("/")
        if self.prefix:
            return f"{self.prefix}/{namespace}/{path}"
        return f"{namespace}/{path}"

    def _get_version(self) -> int:
        """Get current version number (milliseconds since epoch)."""
        return int(datetime.now(timezone.utc).timestamp() * 1000)

    def _calculate_md5(self, content: bytes) -> str:
        """Calculate MD5 hash of content."""
        return hashlib.md5(content).hexdigest()

    def health_check(self) -> bool:
        """Check if S3 is accessible."""
        try:
            # Try to head the bucket to check connectivity
            self.s3.head_bucket(Bucket=self.bucket)
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def read_file(
        self, namespace: str, path: str
    ) -> Tuple[bytes, str, datetime, str, int]:
        """
        Read a file from S3.

        Args:
            namespace: Namespace identifier
            path: File path

        Returns:
            Tuple of (content, md5, last_modified, content_type, version)

        Raises:
            FileNotFoundError: If file doesn't exist or is tombstoned
            StorageError: For other S3 errors
        """
        key = self._make_key(namespace, path)
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)

            # Check if tombstoned
            metadata = response.get("Metadata", {})
            if metadata.get("is-deleted") == "true":
                raise FileNotFoundError(f"File is deleted: {namespace}/{path}")

            content = response["Body"].read()
            md5 = metadata.get("content-md5", self._calculate_md5(content))
            last_modified = response["LastModified"]
            content_type = response.get("ContentType", "application/octet-stream")
            version = int(metadata.get("version", "0"))

            logger.debug(
                f"Read file: {namespace}/{path} (md5={md5}, version={version})"
            )
            return content, md5, last_modified, content_type, version

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(f"File not found: {namespace}/{path}")
            logger.error(f"Error reading file {namespace}/{path}: {e}")
            raise StorageError(f"Failed to read file: {e}")

    def write_file(
        self,
        namespace: str,
        path: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        expected_version: int | None = None,
        content_md5: str | None = None,
    ) -> Tuple[bool, str, int]:
        """
        Write a file to S3 with optional conditional write.

        Args:
            namespace: Namespace identifier
            path: File path
            content: File content bytes
            content_type: Content type
            expected_version: Expected version for conditional write
                             - 0 means file must not exist
                             - >0 means file must have this version
                             - None means no version check
            content_md5: Optional MD5 for payload integrity validation

        Returns:
            Tuple of (is_new, md5_hash, version)

        Raises:
            PreconditionFailedError: If conditional write fails
            StorageError: For other S3 errors
        """
        key = self._make_key(namespace, path)
        new_md5 = self._calculate_md5(content)
        version = self._get_version()

        # Validate payload MD5 if provided
        if content_md5 is not None and content_md5 != new_md5:
            raise StorageError(
                f"Content-MD5 mismatch: provided={content_md5}, calculated={new_md5}"
            )

        # Handle conditional write based on version
        if expected_version is not None:
            try:
                # Check current state
                response = self.s3.head_object(Bucket=self.bucket, Key=key)
                current_version = int(response.get("Metadata", {}).get("version", "0"))

                # File exists
                if expected_version == 0:
                    # Expecting new file, but file exists
                    raise PreconditionFailedError(
                        "File already exists (expected version 0)",
                        current_version=str(current_version),
                        provided_version="0",
                    )

                # Expecting specific version, but it doesn't match
                if current_version != expected_version:
                    raise PreconditionFailedError(
                        f"Version mismatch: current={current_version}, expected={expected_version}",
                        current_version=str(current_version),
                        provided_version=str(expected_version),
                    )

                is_new = False

            except ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    # File doesn't exist
                    if expected_version != 0:
                        # Expected file to exist with specific version
                        raise PreconditionFailedError(
                            f"File does not exist (expected version {expected_version})",
                            current_version="none",
                            provided_version=str(expected_version),
                        )
                    is_new = True
                else:
                    raise StorageError(f"Failed to check file existence: {e}")
        else:
            # No conditional write, check if file exists
            try:
                self.s3.head_object(Bucket=self.bucket, Key=key)
                is_new = False
            except ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    is_new = True
                else:
                    raise StorageError(f"Failed to check file existence: {e}")

        # Write the file
        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                Metadata={
                    "content-md5": new_md5,
                    "version": str(version),
                    "is-deleted": "false",
                },
            )

            # Update sync index
            self._update_sync_index(
                namespace,
                path,
                FileMetadata(
                    md5=new_md5,
                    last_modified=datetime.now(timezone.utc),
                    size=len(content),
                    version=version,
                    is_deleted=False,
                ),
            )

            logger.info(
                f"{'Created' if is_new else 'Updated'} file: {namespace}/{path} "
                f"(md5={new_md5}, version={version})"
            )
            return is_new, new_md5, version

        except Exception as e:
            logger.error(f"Error writing file {namespace}/{path}: {e}")
            raise StorageError(f"Failed to write file: {e}")

    def delete_file(
        self, namespace: str, path: str, expected_version: int | None = None
    ) -> None:
        """
        Delete a file by creating a tombstone.

        Args:
            namespace: Namespace identifier
            path: File path
            expected_version: Optional expected version for conditional delete

        Raises:
            FileNotFoundError: If file doesn't exist
            PreconditionFailedError: If conditional delete fails
            StorageError: For other S3 errors
        """
        key = self._make_key(namespace, path)
        version = self._get_version()

        try:
            # Get current file metadata
            response = self.s3.head_object(Bucket=self.bucket, Key=key)
            current_md5 = response.get("Metadata", {}).get("content-md5", "")
            current_version = int(response.get("Metadata", {}).get("version", "0"))

            # Check conditional delete
            if expected_version is not None and current_version != expected_version:
                raise PreconditionFailedError(
                    f"Version mismatch for delete: current={current_version}, expected={expected_version}",
                    current_version=str(current_version),
                    provided_version=str(expected_version),
                )

            # Create tombstone (0-byte object with is-deleted flag)
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=b"",
                Metadata={
                    "content-md5": current_md5,
                    "version": str(version),
                    "is-deleted": "true",
                },
            )

            # Update sync index
            self._update_sync_index(
                namespace,
                path,
                FileMetadata(
                    md5=current_md5,
                    last_modified=datetime.now(timezone.utc),
                    size=0,
                    version=version,
                    is_deleted=True,
                ),
            )

            logger.info(
                f"Deleted (tombstoned) file: {namespace}/{path} (version={version})"
            )

        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                raise FileNotFoundError(f"File not found: {namespace}/{path}")
            logger.error(f"Error deleting file {namespace}/{path}: {e}")
            raise StorageError(f"Failed to delete file: {e}")

    def get_sync_index(self, namespace: str) -> SyncIndexResponse:
        """
        Get the sync index with all file metadata for a namespace.

        Args:
            namespace: Namespace identifier

        Returns:
            SyncIndexResponse with file metadata

        Raises:
            StorageError: For S3 errors
        """
        f"{namespace}/.sync-index.json"
        key = self._make_key(namespace, ".sync-index.json")

        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            content = response["Body"].read()
            data = json.loads(content)

            # Convert to Pydantic models
            files = {
                path: FileMetadata(**metadata)
                for path, metadata in data.get("files", {}).items()
            }

            logger.debug(
                f"Retrieved sync index for namespace: {namespace} ({len(files)} files)"
            )
            return SyncIndexResponse(
                files=files,
                index_last_modified=datetime.fromisoformat(
                    data.get(
                        "index_last_modified", datetime.now(timezone.utc).isoformat()
                    )
                ),
                index_version=data.get("index_version", 0),
            )

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                # No index yet, return empty
                logger.debug(
                    f"No sync index found for namespace: {namespace}, returning empty"
                )
                index_version = self._get_version()
                return SyncIndexResponse(
                    files={},
                    index_last_modified=datetime.now(timezone.utc),
                    index_version=index_version,
                )
            logger.error(f"Error reading sync index for namespace {namespace}: {e}")
            raise StorageError(f"Failed to read sync index: {e}")

    def _update_sync_index(
        self, namespace: str, path: str, metadata: FileMetadata
    ) -> None:
        """
        Update the sync index with new file metadata.

        Note: This uses last-write-wins for index updates. Race conditions are acceptable
        as the individual blobs have strong consistency.

        Args:
            namespace: Namespace identifier
            path: File path
            metadata: File metadata to store
        """
        key = self._make_key(namespace, ".sync-index.json")

        try:
            # Read current index
            try:
                response = self.s3.get_object(Bucket=self.bucket, Key=key)
                content = response["Body"].read()
                data = json.loads(content)
            except ClientError as e:
                if e.response["Error"]["Code"] == "NoSuchKey":
                    data = {"files": {}}
                else:
                    raise

            # Update entry
            data["files"][path] = {
                "md5": metadata.md5,
                "last_modified": metadata.last_modified.isoformat(),
                "size": metadata.size,
                "version": metadata.version,
                "is_deleted": metadata.is_deleted,
            }
            index_version = self._get_version()
            data["index_last_modified"] = datetime.now(timezone.utc).isoformat()
            data["index_version"] = index_version

            # Write back
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(data, indent=2).encode("utf-8"),
                ContentType="application/json",
            )

            logger.debug(
                f"Updated sync index for: {namespace}/{path} (version={metadata.version})"
            )

        except Exception as e:
            # Log but don't fail the operation - index can be eventually consistent
            logger.error(f"Error updating sync index for {namespace}/{path}: {e}")
