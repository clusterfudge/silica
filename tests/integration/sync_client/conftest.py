"""
Integration test fixtures for sync client tests.

These tests use an in-process memory proxy with moto for S3 and mocked auth.
The proxy runs as a real HTTP server (via uvicorn in a thread) to test actual
HTTP communication.
"""

import os
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import boto3
import pytest
import uvicorn
from moto import mock_aws

from silica.developer.memory.proxy_client import MemoryProxyClient
from silica.developer.memory.sync import SyncEngine
from silica.developer.memory.sync_config import SyncConfig

# Test memory proxy configuration
TEST_PROXY_PORT = 18000  # Different from default 8000 to avoid conflicts
TEST_PROXY_HOST = "127.0.0.1"
TEST_PROXY_URL = f"http://{TEST_PROXY_HOST}:{TEST_PROXY_PORT}"
TEST_TOKEN = "test-integration-token"


@pytest.fixture(scope="module")
def mock_env_vars():
    """Mock environment variables for memory proxy."""
    with patch.dict(
        os.environ,
        {
            "AWS_ACCESS_KEY_ID": "test-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret",
            "AWS_REGION": "us-east-1",
            "S3_BUCKET": "test-sync-bucket",
            "S3_PREFIX": "integration-test",
            "HEARE_AUTH_URL": "http://mock-auth",
            "LOG_LEVEL": "ERROR",  # Reduce noise in test output
        },
    ):
        yield


@pytest.fixture(scope="module")
def mock_s3_service(mock_env_vars):
    """Start mocked S3 service."""
    with mock_aws():
        # Create S3 client and bucket
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-sync-bucket")
        yield s3


@pytest.fixture(scope="module")
def mock_auth_service():
    """Mock authentication service."""
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
def memory_proxy_server(mock_s3_service, mock_auth_service):
    """Start memory proxy server in background thread."""
    # Import and configure app
    from silica.memory_proxy.app import app
    from silica.memory_proxy.config import Settings
    from silica.memory_proxy.storage import S3Storage

    # Create storage with mocked S3
    settings = Settings()
    storage = S3Storage(settings)

    # Set storage on app
    app.state.storage = storage

    # Replace module-level storage
    from silica.memory_proxy import app as app_module

    app_module.storage = storage

    # Create uvicorn config
    config = uvicorn.Config(
        app,
        host=TEST_PROXY_HOST,
        port=TEST_PROXY_PORT,
        log_level="error",
        access_log=False,
    )
    server = uvicorn.Server(config)

    # Run server in thread
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to start
    import httpx

    for _ in range(50):  # Try for 5 seconds
        try:
            response = httpx.get(f"{TEST_PROXY_URL}/health", timeout=1)
            if response.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.1)
    else:
        raise RuntimeError("Memory proxy server failed to start")

    yield TEST_PROXY_URL

    # Shutdown happens automatically when thread exits (daemon=True)


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
def sync_client(memory_proxy_server):
    """Create configured sync client."""
    client = MemoryProxyClient(
        base_url=memory_proxy_server,
        token=TEST_TOKEN,
        timeout=30,
        max_retries=3,
    )

    yield client

    client.close()


@pytest.fixture
def memory_sync_engine(sync_client, temp_persona_dir, clean_namespace):
    """Create SyncEngine for memory sync."""
    # Create persona.md
    persona_md = temp_persona_dir / "persona.md"
    persona_md.write_text("Test persona")

    # Use dash instead of slash to avoid URL encoding issues
    config = SyncConfig(
        namespace=f"{clean_namespace}-memory",
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

    # Use dash instead of slash to avoid URL encoding issues
    config = SyncConfig(
        namespace=f"{clean_namespace}-history-{session_id}",
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

        # Use dash instead of slash to avoid URL encoding issues
        namespace_suffix = namespace_suffix.replace("/", "-")
        namespace = (
            f"{clean_namespace}-{namespace_suffix}"
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
        "markers", "integration: Integration tests with in-process memory proxy"
    )
    config.addinivalue_line(
        "markers", "requires_proxy: Tests that need memory proxy service"
    )
    config.addinivalue_line("markers", "slow: Slow-running tests (e.g., performance)")
    config.addinivalue_line("markers", "memory_sync: Memory sync specific tests")
    config.addinivalue_line("markers", "history_sync: History sync specific tests")

    # Wait for server to start
    import httpx

    for _ in range(50):  # Try for 5 seconds
        try:
            response = httpx.get(f"{TEST_PROXY_URL}/health", timeout=1)
            if response.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.1)
    else:
        raise RuntimeError("Memory proxy server failed to start")
