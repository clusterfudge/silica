"""
Integration test fixtures for sync client tests.

These tests require a running memory proxy service.
Configure via environment variables:
  - MEMORY_PROXY_PORT (default: 8000)
  - MEMORY_PROXY_HOST (default: localhost)
  - MEMORY_PROXY_TOKEN (default: test-integration-token)

To run the tests:
1. Start memory proxy: python -m silica.memory_proxy.app
2. Run tests: pytest tests/integration/sync_client/ -v
"""

import os
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from silica.developer.memory.proxy_client import MemoryProxyClient
from silica.developer.memory.sync import SyncEngine
from silica.developer.memory.sync_config import SyncConfig

# Memory proxy configuration from environment
PROXY_PORT = int(os.getenv("MEMORY_PROXY_PORT", "8000"))
PROXY_HOST = os.getenv("MEMORY_PROXY_HOST", "localhost")
PROXY_BASE_URL = f"http://{PROXY_HOST}:{PROXY_PORT}"
TEST_TOKEN = os.getenv("MEMORY_PROXY_TOKEN", "test-integration-token")


@pytest.fixture(scope="module")
def check_proxy_available():
    """Verify memory proxy is accessible before running tests."""
    import httpx

    try:
        response = httpx.get(f"{PROXY_BASE_URL}/health", timeout=5)
        if response.status_code != 200:
            pytest.skip(f"Memory proxy not healthy at {PROXY_BASE_URL}")
    except Exception as e:
        pytest.skip(
            f"Memory proxy not accessible at {PROXY_BASE_URL}: {e}\n"
            f"Start the service with: python -m silica.memory_proxy.app"
        )


@pytest.fixture
def clean_namespace(check_proxy_available):
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
def sync_client(check_proxy_available):
    """Create configured sync client."""
    client = MemoryProxyClient(
        base_url=PROXY_BASE_URL,
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
