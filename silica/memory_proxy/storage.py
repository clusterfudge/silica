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
    """Conditional operation failed (MD5 mismatch)."""

    def __init__(self, message: str, current_md5: str, provided_md5: str):
        super().__init__(message)
        self.current_md5 = current_md5
        self.provided_md5 = provided_md5


class S3Storage:
    """Handles all S3 operations for the Memory Proxy service."""

    SYNC_INDEX_KEY = ".sync-index.json"
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

    def _make_key(self, path: str) -> str:
        """Convert a file path to an S3 key with prefix."""
        # Remove leading slash if present
        path = path.lstrip("/")
        return f"{self.prefix}/{path}" if self.prefix else path

    def _calculate_md5(self, content: bytes) -> str:
        """Calculate MD5 hash of content."""
        return hashlib.md5(content).hexdigest()

    def health_check(self) -> bool:
        """Check if S3 is accessible."""
        try:
            # Try to head the sync index (or bucket if index doesn't exist)
            key = self._make_key(self.SYNC_INDEX_KEY)
            try:
                self.s3.head_object(Bucket=self.bucket, Key=key)
            except ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    # Index doesn't exist yet, but S3 is accessible
                    # Try to head the bucket instead
                    self.s3.head_bucket(Bucket=self.bucket)
                else:
                    raise
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def read_file(self, path: str) -> Tuple[bytes, str, datetime, str]:
        """
        Read a file from S3.

        Returns:
            Tuple of (content, md5, last_modified, content_type)

        Raises:
            FileNotFoundError: If file doesn't exist or is tombstoned
            StorageError: For other S3 errors
        """
        key = self._make_key(path)
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)

            # Check if tombstoned
            metadata = response.get("Metadata", {})
            if metadata.get("is-deleted") == "true":
                raise FileNotFoundError(f"File is deleted: {path}")

            content = response["Body"].read()
            md5 = metadata.get("content-md5", self._calculate_md5(content))
            last_modified = response["LastModified"]
            content_type = response.get("ContentType", "application/octet-stream")

            return content, md5, last_modified, content_type

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(f"File not found: {path}")
            logger.error(f"Error reading file {path}: {e}")
            raise StorageError(f"Failed to read file: {e}")

    def write_file(
        self,
        path: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        expected_md5: str | None = None,
    ) -> Tuple[bool, str]:
        """
        Write a file to S3 with optional conditional write.

        Args:
            path: File path
            content: File content bytes
            content_type: Content type
            expected_md5: Expected MD5 for conditional write (or SENTINEL_NEW_FILE for new files)

        Returns:
            Tuple of (is_new, md5_hash)

        Raises:
            PreconditionFailedError: If conditional write fails
            StorageError: For other S3 errors
        """
        key = self._make_key(path)
        new_md5 = self._calculate_md5(content)

        # Handle conditional write
        if expected_md5 is not None:
            try:
                # Check current state
                response = self.s3.head_object(Bucket=self.bucket, Key=key)
                current_md5 = response.get("Metadata", {}).get("content-md5")

                # If expecting new file, but file exists
                if expected_md5 == self.SENTINEL_NEW_FILE:
                    raise PreconditionFailedError(
                        "File already exists",
                        current_md5=current_md5 or "unknown",
                        provided_md5=expected_md5,
                    )

                # If expecting specific MD5, but it doesn't match
                if (
                    expected_md5 != self.SENTINEL_NEW_FILE
                    and current_md5 != expected_md5
                ):
                    raise PreconditionFailedError(
                        "Content-MD5 mismatch",
                        current_md5=current_md5 or "unknown",
                        provided_md5=expected_md5,
                    )

                is_new = False

            except ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    # File doesn't exist
                    if expected_md5 != self.SENTINEL_NEW_FILE:
                        # Expected file to exist for update
                        raise PreconditionFailedError(
                            "File does not exist",
                            current_md5="none",
                            provided_md5=expected_md5,
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
                    "is-deleted": "false",
                },
            )

            # Update sync index
            self._update_sync_index(
                path,
                FileMetadata(
                    md5=new_md5,
                    last_modified=datetime.now(timezone.utc),
                    size=len(content),
                    is_deleted=False,
                ),
            )

            logger.info(
                f"{'Created' if is_new else 'Updated'} file: {path} (md5={new_md5})"
            )
            return is_new, new_md5

        except Exception as e:
            logger.error(f"Error writing file {path}: {e}")
            raise StorageError(f"Failed to write file: {e}")

    def delete_file(self, path: str, expected_md5: str | None = None) -> None:
        """
        Delete a file by creating a tombstone.

        Args:
            path: File path
            expected_md5: Optional expected MD5 for conditional delete

        Raises:
            FileNotFoundError: If file doesn't exist
            PreconditionFailedError: If conditional delete fails
            StorageError: For other S3 errors
        """
        key = self._make_key(path)

        try:
            # Get current file metadata
            response = self.s3.head_object(Bucket=self.bucket, Key=key)
            current_md5 = response.get("Metadata", {}).get("content-md5", "")

            # Check conditional delete
            if expected_md5 is not None and current_md5 != expected_md5:
                raise PreconditionFailedError(
                    "Content-MD5 mismatch for delete",
                    current_md5=current_md5,
                    provided_md5=expected_md5,
                )

            # Create tombstone (0-byte object with is-deleted flag)
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=b"",
                Metadata={
                    "content-md5": current_md5,
                    "is-deleted": "true",
                },
            )

            # Update sync index
            self._update_sync_index(
                path,
                FileMetadata(
                    md5=current_md5,
                    last_modified=datetime.now(timezone.utc),
                    size=0,
                    is_deleted=True,
                ),
            )

            logger.info(f"Deleted (tombstoned) file: {path}")

        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                raise FileNotFoundError(f"File not found: {path}")
            logger.error(f"Error deleting file {path}: {e}")
            raise StorageError(f"Failed to delete file: {e}")

    def get_sync_index(self) -> SyncIndexResponse:
        """
        Get the sync index with all file metadata.

        Returns:
            SyncIndexResponse with file metadata

        Raises:
            StorageError: For S3 errors
        """
        key = self._make_key(self.SYNC_INDEX_KEY)

        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            content = response["Body"].read()
            data = json.loads(content)

            # Convert to Pydantic models
            files = {
                path: FileMetadata(**metadata)
                for path, metadata in data.get("files", {}).items()
            }

            return SyncIndexResponse(
                files=files,
                index_last_modified=datetime.fromisoformat(
                    data.get(
                        "index_last_modified", datetime.now(timezone.utc).isoformat()
                    )
                ),
            )

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                # No index yet, return empty
                return SyncIndexResponse(
                    files={}, index_last_modified=datetime.now(timezone.utc)
                )
            logger.error(f"Error reading sync index: {e}")
            raise StorageError(f"Failed to read sync index: {e}")

    def _update_sync_index(self, path: str, metadata: FileMetadata) -> None:
        """
        Update the sync index with new file metadata.

        Note: This uses last-write-wins for index updates. Race conditions are acceptable
        as the individual blobs have strong consistency.

        Args:
            path: File path
            metadata: File metadata to store
        """
        key = self._make_key(self.SYNC_INDEX_KEY)

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
                "is_deleted": metadata.is_deleted,
            }
            data["index_last_modified"] = datetime.now(timezone.utc).isoformat()

            # Write back
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(data, indent=2).encode("utf-8"),
                ContentType="application/json",
            )

            logger.debug(f"Updated sync index for: {path}")

        except Exception as e:
            # Log but don't fail the operation - index can be eventually consistent
            logger.error(f"Error updating sync index for {path}: {e}")
