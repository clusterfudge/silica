"""Tests for conflict resolution and retry logic."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from silica.developer.memory.conflict_resolver import (
    ConflictResolver,
    ConflictResolutionError,
)
from silica.developer.memory.sync import SyncEngine
from silica.developer.memory.sync_coordinator import sync_with_retry
from silica.developer.memory.exceptions import SyncExhaustedError
from unittest.mock import patch
from starlette.testclient import TestClient


class MockConflictResolver(ConflictResolver):
    """Mock conflict resolver for testing."""

    def __init__(self, strategy: str = "local"):
        """Initialize mock resolver.

        Args:
            strategy: Resolution strategy - "local", "remote", or "error"
        """
        if strategy not in ("local", "remote", "error"):
            raise ValueError(f"Invalid strategy: {strategy}")
        self.strategy = strategy

    def resolve_conflict(
        self,
        path: str,
        local_content: bytes,
        remote_content: bytes,
        local_metadata: dict | None = None,
        remote_metadata: dict | None = None,
    ) -> bytes:
        """Resolve conflict based on strategy."""
        if self.strategy == "error":
            raise ConflictResolutionError(f"Mock error for {path}")
        elif self.strategy == "local":
            return local_content
        else:  # remote
            return remote_content


class TestConflictResolver:
    """Tests for ConflictResolver interface and implementations."""

    def test_mock_resolver_local_strategy(self):
        """Test mock resolver with local strategy."""
        resolver = MockConflictResolver(strategy="local")
        result = resolver.resolve_conflict(
            path="test.md",
            local_content=b"local",
            remote_content=b"remote",
        )
        assert result == b"local"

    def test_mock_resolver_remote_strategy(self):
        """Test mock resolver with remote strategy."""
        resolver = MockConflictResolver(strategy="remote")
        result = resolver.resolve_conflict(
            path="test.md",
            local_content=b"local",
            remote_content=b"remote",
        )
        assert result == b"remote"

    def test_mock_resolver_error_strategy(self):
        """Test mock resolver with error strategy."""
        resolver = MockConflictResolver(strategy="error")
        with pytest.raises(ConflictResolutionError):
            resolver.resolve_conflict(
                path="test.md",
                local_content=b"local",
                remote_content=b"remote",
            )

    def test_mock_resolver_invalid_strategy(self):
        """Test mock resolver with invalid strategy."""
        with pytest.raises(ValueError):
            MockConflictResolver(strategy="invalid")


@pytest.fixture
def temp_dir():
    """Create temporary directory."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_memory_proxy_app():
    """Create mocked memory proxy app."""
    from moto import mock_aws
    import os
    import sys

    # Mock S3
    with mock_aws():
        import boto3

        s3_client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        bucket = "test-bucket"
        s3_client.create_bucket(Bucket=bucket)

        # Set environment
        env_vars = {
            "S3_BUCKET": bucket,
            "AWS_REGION": "us-east-1",
            "AWS_ACCESS_KEY_ID": "testing",
            "AWS_SECRET_ACCESS_KEY": "testing",
            "S3_PREFIX": "test",
            "HEARE_AUTH_URL": "http://test:8080",
            "LOG_LEVEL": "ERROR",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            # Force reload
            modules_to_remove = [
                key
                for key in sys.modules.keys()
                if key.startswith("silica.memory_proxy")
            ]
            for module in modules_to_remove:
                del sys.modules[module]

            from silica.memory_proxy import app as app_module
            from silica.memory_proxy import auth as auth_module

            async def mock_verify_token():
                return {"user_id": "test", "email": "test@test.com"}

            app_module.app.dependency_overrides[auth_module.verify_token] = (
                mock_verify_token
            )

            yield app_module.app

            app_module.app.dependency_overrides.clear()


@pytest.fixture
def test_client(mock_memory_proxy_app):
    """Create test client."""
    return TestClient(mock_memory_proxy_app)


@pytest.fixture
def proxy_client(test_client):
    """Create proxy client with test client."""
    from silica.developer.memory.proxy_client import MemoryProxyClient

    client = MemoryProxyClient(base_url="http://testserver", token="test")
    client.client = test_client
    yield client
    client.close()


@pytest.fixture
def sync_engine_with_resolver(temp_dir, proxy_client):
    """Create sync engine with mock conflict resolver."""
    from silica.developer.memory.sync_config import SyncConfig

    resolver = MockConflictResolver(strategy="local")
    config = SyncConfig(
        namespace="test",
        scan_paths=[temp_dir / "memory"],
        index_file=temp_dir / ".sync-index.json",
    )
    engine = SyncEngine(
        client=proxy_client,
        config=config,
        conflict_resolver=resolver,
    )
    return engine


class TestConflictResolution:
    """Integration tests for conflict resolution."""

    def test_resolve_conflicts_method(
        self, sync_engine_with_resolver, temp_dir, proxy_client
    ):
        """Test that resolve_conflicts works end-to-end."""
        # Create local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        test_file = memory_dir / "test.md"
        test_file.write_text("Local version")

        # Upload it first
        plan1 = sync_engine_with_resolver.analyze_sync_operations()
        sync_engine_with_resolver.execute_sync(plan1, show_progress=False)

        # Modify locally
        test_file.write_text("Local modification")

        # Modify remotely
        remote_index = proxy_client.get_sync_index("test")
        version = remote_index.files["memory/test.md"].version
        proxy_client.write_blob(
            "test", "memory/test.md", b"Remote modification", expected_version=version
        )

        # Detect conflict
        plan2 = sync_engine_with_resolver.analyze_sync_operations()
        assert len(plan2.conflicts) == 1

        # Resolve conflicts
        resolved_uploads = sync_engine_with_resolver.resolve_conflicts(plan2.conflicts)

        assert len(resolved_uploads) == 1
        assert resolved_uploads[0].type == "upload"
        assert resolved_uploads[0].path == "memory/test.md"

        # File should contain local content (mock resolver uses local strategy)
        assert test_file.read_text() == "Local modification"

    def test_sync_with_retry_handles_conflicts(
        self, sync_engine_with_resolver, temp_dir, proxy_client
    ):
        """Test that sync_with_retry automatically resolves conflicts."""
        # Create local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        test_file = memory_dir / "test.md"
        test_file.write_text("Local version")

        # First sync
        result1 = sync_with_retry(sync_engine_with_resolver, max_retries=3)
        assert len(result1.succeeded) == 1

        # Modify both sides
        test_file.write_text("Local modification")
        remote_index = proxy_client.get_sync_index("test")
        version = remote_index.files["memory/test.md"].version
        proxy_client.write_blob(
            "test", "memory/test.md", b"Remote modification", expected_version=version
        )

        # Sync should automatically resolve conflict
        result2 = sync_with_retry(sync_engine_with_resolver, max_retries=3)
        assert len(result2.succeeded) == 1
        assert result2.succeeded[0].path == "memory/test.md"

    def test_sync_without_resolver_raises_error(self, temp_dir, proxy_client):
        """Test that sync_with_retry requires a resolver."""
        from silica.developer.memory.sync_config import SyncConfig

        config = SyncConfig(
            namespace="test",
            scan_paths=[temp_dir / "memory"],
            index_file=temp_dir / ".sync-index.json",
        )
        engine = SyncEngine(
            client=proxy_client,
            config=config,
            conflict_resolver=None,  # No resolver
        )

        with pytest.raises(ValueError, match="conflict_resolver"):
            sync_with_retry(engine, max_retries=3)

    def test_sync_with_retry_exhaustion(
        self, sync_engine_with_resolver, temp_dir, proxy_client
    ):
        """Test that sync_with_retry exhausts retries on persistent errors."""
        # Create a file so there's something to sync
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        test_file = memory_dir / "test.md"
        test_file.write_text("Test content")

        # Mock the execute_sync to always fail
        sync_engine_with_resolver.execute_sync

        def failing_execute(*args, **kwargs):
            from silica.developer.memory.sync import SyncResult, SyncOperationDetail

            result = SyncResult()
            result.failed.append(
                SyncOperationDetail(
                    type="upload",
                    path="memory/test.md",
                    reason="Mock failure",
                )
            )
            return result

        sync_engine_with_resolver.execute_sync = failing_execute

        # Should exhaust retries
        with pytest.raises(SyncExhaustedError, match="failed after 2 attempts"):
            sync_with_retry(sync_engine_with_resolver, max_retries=2)

    def test_sync_with_retry_on_version_conflict(
        self, sync_engine_with_resolver, temp_dir, proxy_client
    ):
        """Test that sync retries on version conflicts (412)."""
        # Create and sync a file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        test_file = memory_dir / "test.md"
        test_file.write_text("Original")

        result1 = sync_with_retry(sync_engine_with_resolver, max_retries=3)
        assert len(result1.succeeded) == 1

        # Modify locally
        test_file.write_text("Local mod")

        # Simulate version conflict by modifying remote twice
        # (once before our upload, causing 412)
        remote_index = proxy_client.get_sync_index("test")
        version = remote_index.files["memory/test.md"].version

        # Remote changes
        proxy_client.write_blob(
            "test", "memory/test.md", b"Remote mod 1", expected_version=version
        )

        # Now our sync will get 412 when trying to upload
        # But it should retry and eventually succeed
        result2 = sync_with_retry(sync_engine_with_resolver, max_retries=3)

        # Should have resolved the conflict and uploaded
        assert len(result2.succeeded) == 1
