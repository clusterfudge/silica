"""
Integration test fixtures for sync client tests.

These tests use a mocked memory proxy service with moto for S3.
"""

import os
import pytest
import boto3
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch
from moto import mock_aws
from starlette.testclient import TestClient

from silica.developer.memory.sync import SyncEngine
from silica.developer.memory.sync_config import SyncConfig


@pytest.fixture(scope="module")
def mock_env_vars():
    """Mock environment variables for testing."""
    with patch.dict(
        os.environ,
        {
            "AWS_ACCESS_KEY_ID": "test-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret",
            "AWS_REGION": "us-east-1",
            "S3_BUCKET": "test-sync-bucket",
            "S3_PREFIX": "sync-test",
            "HEARE_AUTH_URL": "http://test-auth",
            "LOG_LEVEL": "DEBUG",
        },
    ):
        yield


@pytest.fixture(scope="module")
def mock_s3(mock_env_vars):
    """Mock S3 with moto."""
    with mock_aws():
        # Create S3 client and bucket
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-sync-bucket")
        yield s3


@pytest.fixture(scope="module")
def mock_auth_success():
    """Mock successful authentication."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"user_id": "test-user"}

    async def mock_post(*args, **kwargs):
        return mock_response

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=mock_post
        )
        yield mock_client


@pytest.fixture(scope="module")
def memory_proxy_service(mock_s3, mock_auth_success):
    """Create test memory proxy service with mocked dependencies."""
    # Import app after env vars are set
    from silica.memory_proxy.app import app
    from silica.memory_proxy.config import Settings
    from silica.memory_proxy.storage import S3Storage

    # Recreate storage with mocked S3
    settings = Settings()
    app.state.storage = S3Storage(settings)

    # Replace the module-level storage variable
    from silica.memory_proxy import app as app_module

    app_module.storage = app.state.storage

    # Create test client
    client = TestClient(app)

    yield client


@pytest.fixture
def clean_namespace():
    """Provide a clean namespace for each test."""
    namespace = f"test-{uuid4().hex[:8]}"
    yield namespace


@pytest.fixture
def temp_persona_dir():
    """Create temporary persona directory structure."""
    with TemporaryDirectory() as tmpdir:
        persona_dir = Path(tmpdir) / "personas" / "test-persona"
        persona_dir.mkdir(parents=True)

        # Create standard structure
        (persona_dir / "memory").mkdir()
        (persona_dir / "history").mkdir()

        yield persona_dir


@pytest.fixture
def auth_headers():
    """Authentication headers for test requests."""
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def sync_client(memory_proxy_service, auth_headers):
    """Create configured sync client that uses the test memory proxy."""

    # Create adapter that makes TestClient compatible with MemoryProxyClient
    class TestMemoryProxyClient:
        def __init__(self, test_client, auth_headers):
            self._client = test_client
            self._headers = auth_headers
            self.base_url = "http://testserver"

        def write_blob(
            self,
            namespace,
            path,
            content,
            expected_version,
            content_type="application/octet-stream",
            content_md5=None,
        ):
            """Write blob via test client."""
            headers = {
                **self._headers,
                "If-Match-Version": str(expected_version),
                "Content-Type": content_type,
            }
            if content_md5:
                headers["Content-MD5"] = content_md5

            response = self._client.put(
                f"/blob/{namespace}/{path}",
                content=content,
                headers=headers,
            )

            if response.status_code in (200, 201):
                # Match the signature of the real client - return tuple
                json_response = response.json()
                is_new = response.status_code == 201
                etag = response.headers.get("ETag", "").strip('"')
                version = int(response.headers.get("X-Version", 0))

                # Convert JSON response to SyncIndexResponse
                from silica.developer.memory.proxy_client import (
                    SyncIndexResponse,
                    FileMetadata,
                )

                files = {}
                for file_path, meta in json_response.get("files", {}).items():
                    files[file_path] = FileMetadata(
                        md5=meta["md5"],
                        last_modified=meta["last_modified"],
                        size=meta["size"],
                        version=meta["version"],
                        is_deleted=meta.get("is_deleted", False),
                    )
                sync_index = SyncIndexResponse(
                    files=files,
                    index_version=json_response.get("index_version", version),
                    index_last_modified=json_response.get(
                        "index_last_modified", datetime.now(timezone.utc).isoformat()
                    ),
                )

                return (is_new, etag, version, sync_index)
            elif response.status_code == 412:
                from silica.developer.memory.proxy_client import MemoryProxyError

                raise MemoryProxyError(f"Version conflict: {response.text}")
            else:
                from silica.developer.memory.proxy_client import MemoryProxyError

                raise MemoryProxyError(
                    f"Failed to write blob: {response.status_code} {response.text}"
                )

        def read_blob(self, namespace, path):
            """Read blob via test client."""
            response = self._client.get(
                f"/blob/{namespace}/{path}",
                headers=self._headers,
            )

            if response.status_code == 200:
                return {
                    "content": response.content,
                    "md5": response.headers.get("ETag", "").strip('"'),
                    "version": int(response.headers.get("X-Version", 0)),
                    "content_type": response.headers.get("Content-Type", ""),
                }
            elif response.status_code == 404:
                from silica.developer.memory.proxy_client import MemoryProxyError

                raise MemoryProxyError(f"File not found: {namespace}/{path}")
            else:
                from silica.developer.memory.proxy_client import MemoryProxyError

                raise MemoryProxyError(
                    f"Failed to read blob: {response.status_code} {response.text}"
                )

        def delete_blob(self, namespace, path, expected_version=None):
            """Delete blob via test client."""
            headers = {**self._headers}
            if expected_version is not None:
                headers["If-Match-Version"] = str(expected_version)

            response = self._client.delete(
                f"/blob/{namespace}/{path}",
                headers=headers,
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                from silica.developer.memory.proxy_client import MemoryProxyError

                raise MemoryProxyError(f"File not found: {namespace}/{path}")
            elif response.status_code == 412:
                from silica.developer.memory.proxy_client import MemoryProxyError

                raise MemoryProxyError(f"Version conflict: {response.text}")
            else:
                from silica.developer.memory.proxy_client import MemoryProxyError

                raise MemoryProxyError(
                    f"Failed to delete blob: {response.status_code} {response.text}"
                )

        def get_sync_index(self, namespace):
            """Get sync index via test client."""
            response = self._client.get(
                f"/sync/{namespace}",
                headers=self._headers,
            )

            if response.status_code == 200:
                data = response.json()
                # Convert to SyncIndexResponse format expected by sync engine
                from silica.developer.memory.proxy_client import (
                    SyncIndexResponse,
                    FileMetadata,
                )

                files = {}
                for path, meta in data.get("files", {}).items():
                    files[path] = FileMetadata(
                        md5=meta["md5"],
                        last_modified=meta["last_modified"],
                        size=meta["size"],
                        version=meta["version"],
                        is_deleted=meta.get("is_deleted", False),
                    )
                return SyncIndexResponse(
                    files=files,
                    index_version=data.get("index_version", 1),
                    index_last_modified=data.get("index_last_modified", ""),
                )
            elif response.status_code == 404:
                # Namespace doesn't exist yet - return empty index
                from silica.developer.memory.proxy_client import SyncIndexResponse

                return SyncIndexResponse(
                    files={},
                    index_version=0,
                    index_last_modified=datetime.now(timezone.utc),
                )
            else:
                from silica.developer.memory.proxy_client import MemoryProxyError

                raise MemoryProxyError(
                    f"Failed to get sync index: {response.status_code} {response.text}"
                )

        def close(self):
            """No-op for test client."""

    client = TestMemoryProxyClient(memory_proxy_service, auth_headers)
    yield client
    client.close()


@pytest.fixture
def memory_sync_engine(sync_client, temp_persona_dir, clean_namespace):
    """Create SyncEngine for memory sync."""
    # Create persona.md
    persona_md = temp_persona_dir / "persona.md"
    persona_md.write_text("Test persona")

    config = SyncConfig(
        namespace=f"{clean_namespace}/memory",
        scan_paths=[
            temp_persona_dir / "memory",
            persona_md,
        ],
        index_file=temp_persona_dir / ".sync-index-memory.json",
        base_dir=temp_persona_dir,
    )

    engine = SyncEngine(client=sync_client, config=config)

    yield engine


@pytest.fixture
def history_sync_engine(sync_client, temp_persona_dir, clean_namespace):
    """Create SyncEngine for history sync."""
    session_id = "session-test-001"
    session_dir = temp_persona_dir / "history" / session_id
    session_dir.mkdir(parents=True)

    config = SyncConfig(
        namespace=f"{clean_namespace}/history/{session_id}",
        scan_paths=[session_dir],
        index_file=session_dir / ".sync-index-history.json",
        base_dir=temp_persona_dir,
    )

    engine = SyncEngine(client=sync_client, config=config)

    yield engine


@pytest.fixture
def create_local_files(temp_persona_dir):
    """Helper to create local test files."""

    def _create_files(files_dict):
        """
        Create files in temp directory.

        Args:
            files_dict: Dict mapping paths to content
                       e.g., {"memory/test.md": "content"}
        """
        for path, content in files_dict.items():
            file_path = temp_persona_dir / path
            file_path.parent.mkdir(parents=True, exist_ok=True)

            if isinstance(content, str):
                file_path.write_text(content)
            else:
                file_path.write_bytes(content)

        return temp_persona_dir

    return _create_files


@pytest.fixture
def create_remote_files(sync_client, clean_namespace):
    """Helper to create remote test files."""

    def _create_files(namespace_suffix, files_dict):
        """
        Create files on remote.

        Args:
            namespace_suffix: e.g., "/memory" or "/history/session-test-001"
            files_dict: Dict mapping paths to content
        """
        # Remove leading slash if present for consistency
        if namespace_suffix.startswith("/"):
            namespace_suffix = namespace_suffix[1:]

        namespace = (
            f"{clean_namespace}/{namespace_suffix}"
            if namespace_suffix
            else clean_namespace
        )

        for path, content in files_dict.items():
            if isinstance(content, str):
                content = content.encode()

            sync_client.write_blob(
                namespace=namespace,
                path=path,
                content=content,
                expected_version=0,  # New file
            )

        return namespace

    return _create_files


# Pytest configuration
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: Integration tests requiring memory proxy"
    )
    config.addinivalue_line(
        "markers", "requires_proxy: Tests that need memory proxy service running"
    )
    config.addinivalue_line("markers", "slow: Slow-running tests (e.g., performance)")
    config.addinivalue_line("markers", "memory_sync: Memory sync specific tests")
    config.addinivalue_line("markers", "history_sync: History sync specific tests")
