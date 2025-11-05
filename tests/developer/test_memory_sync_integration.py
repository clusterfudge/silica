"""Integration tests for memory sync with real memory proxy service and mocked S3.

These tests:
1. Start a real FastAPI memory proxy service in-process
2. Use moto to mock S3 backend
3. Mock the authentication dependency
4. Use MemoryProxyClient to interact with service
5. Use SyncEngine to perform actual sync operations
6. Verify end-to-end sync workflows
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from moto import mock_aws
from starlette.testclient import TestClient


@pytest.fixture
def mock_s3():
    """Set up mocked S3 environment."""
    with mock_aws():
        import boto3

        # Create S3 client
        s3_client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )

        # Create bucket
        bucket_name = "test-memory-proxy-bucket"
        s3_client.create_bucket(Bucket=bucket_name)

        yield {
            "bucket": bucket_name,
            "region": "us-east-1",
            "access_key": "testing",
            "secret_key": "testing",
        }


@pytest.fixture
def memory_proxy_app(mock_s3):
    """Create FastAPI app with mocked S3 backend and mocked auth."""
    # Set environment variables BEFORE importing app module
    env_vars = {
        "S3_BUCKET": mock_s3["bucket"],
        "AWS_REGION": mock_s3["region"],
        "AWS_ACCESS_KEY_ID": mock_s3["access_key"],
        "AWS_SECRET_ACCESS_KEY": mock_s3["secret_key"],
        "S3_PREFIX": "test-prefix",
        "HEARE_AUTH_URL": "http://test-auth-service:8080",
        "LOG_LEVEL": "ERROR",
    }

    # Patch environment
    with patch.dict(os.environ, env_vars, clear=False):
        # Force reload of the app module to pick up new settings
        # Remove cached modules
        modules_to_remove = [
            key for key in sys.modules.keys() if key.startswith("silica.memory_proxy")
        ]
        for module in modules_to_remove:
            del sys.modules[module]

        # Now import with patched environment
        from silica.memory_proxy.app import app
        from silica.memory_proxy.auth import verify_token

        # Mock the authentication dependency
        async def mock_verify_token():
            return {"user_id": "test_user", "email": "test@example.com"}

        # Replace the verify_token dependency
        app.dependency_overrides[verify_token] = mock_verify_token

        yield app

        # Cleanup
        app.dependency_overrides.clear()


@pytest.fixture
def test_client(memory_proxy_app):
    """Create test client for the memory proxy."""
    client = TestClient(memory_proxy_app)
    yield client
    client.close()


@pytest.fixture
def temp_persona_dir():
    """Create temporary persona directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        persona_dir = Path(tmpdir) / "personas" / "test-persona"
        persona_dir.mkdir(parents=True)

        # Create memory and history directories
        (persona_dir / "memory").mkdir()
        (persona_dir / "history").mkdir()

        yield persona_dir


@pytest.fixture
def proxy_client(test_client):
    """Create MemoryProxyClient that uses the test client."""
    from silica.developer.memory.proxy_client import MemoryProxyClient

    # Create client with test URL
    client = MemoryProxyClient(
        base_url="http://testserver",
        token="test-token-123",  # Any token works with mocked auth
    )

    # Replace the httpx client with test client
    client.client = test_client

    yield client

    client.close()


@pytest.fixture
def sync_engine(proxy_client, temp_persona_dir):
    """Create SyncEngine with test client and temp directory."""
    from silica.developer.memory.sync import SyncEngine

    return SyncEngine(
        client=proxy_client, local_base_dir=temp_persona_dir, namespace="test-persona"
    )


class TestEndToEndSync:
    """Test complete sync workflows."""

    def test_health_check(self, proxy_client):
        """Test that we can connect to the memory proxy."""
        is_healthy = proxy_client.health_check()
        assert is_healthy is True

    def test_first_sync_upload_local_files(
        self, sync_engine, temp_persona_dir, proxy_client
    ):
        """Test first sync: upload local files to empty remote."""
        # Create local files
        memory_dir = temp_persona_dir / "memory"
        (memory_dir / "file1.md").write_text("Content 1")
        (memory_dir / "file2.md").write_text("Content 2")
        (temp_persona_dir / "persona.md").write_text("Persona content")

        # Analyze what needs to be synced
        plan = sync_engine.analyze_sync_operations()

        # Should have 3 uploads (2 memory files + persona.md)
        assert len(plan.upload) == 3
        assert len(plan.download) == 0
        assert len(plan.conflicts) == 0

        # Execute sync
        result = sync_engine.execute_sync(plan, show_progress=False)

        # All should succeed
        assert len(result.succeeded) == 3
        assert len(result.failed) == 0
        assert result.success_rate == 100.0

        # Verify files are in remote
        remote_index = proxy_client.get_sync_index("test-persona")
        assert len(remote_index.files) == 3

        paths = set(remote_index.files.keys())
        assert "memory/file1.md" in paths
        assert "memory/file2.md" in paths
        assert "persona.md" in paths

    def test_download_remote_files(self, sync_engine, temp_persona_dir, proxy_client):
        """Test downloading files from remote when local is empty."""
        # Upload files directly to remote (expected_version=0 means create new)
        proxy_client.write_blob(
            "test-persona", "memory/remote1.md", b"Remote content 1", expected_version=0
        )
        proxy_client.write_blob(
            "test-persona", "memory/remote2.md", b"Remote content 2", expected_version=0
        )

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # Should have 2 downloads
        assert len(plan.download) == 2
        assert len(plan.upload) == 0

        # Execute sync
        result = sync_engine.execute_sync(plan, show_progress=False)

        # Should succeed
        assert len(result.succeeded) == 2
        assert len(result.failed) == 0

        # Verify files exist locally
        memory_dir = temp_persona_dir / "memory"
        assert (memory_dir / "remote1.md").exists()
        assert (memory_dir / "remote2.md").exists()
        assert (memory_dir / "remote1.md").read_text() == "Remote content 1"
        assert (memory_dir / "remote2.md").read_text() == "Remote content 2"

    def test_bidirectional_sync(self, sync_engine, temp_persona_dir, proxy_client):
        """Test syncing with both local and remote files."""
        # Create local file
        memory_dir = temp_persona_dir / "memory"
        (memory_dir / "local.md").write_text("Local content")

        # Create remote file (expected_version=0 means create new)
        proxy_client.write_blob(
            "test-persona", "memory/remote.md", b"Remote content", expected_version=0
        )

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # Should have 1 upload and 1 download
        assert len(plan.upload) == 1
        assert len(plan.download) == 1
        assert len(plan.conflicts) == 0

        # Execute sync
        result = sync_engine.execute_sync(plan, show_progress=False)

        # Should succeed
        assert len(result.succeeded) == 2
        assert len(result.failed) == 0

        # Verify both files exist locally
        assert (memory_dir / "local.md").exists()
        assert (memory_dir / "remote.md").exists()

        # Verify both files exist remotely
        remote_index = proxy_client.get_sync_index("test-persona")
        paths = set(remote_index.files.keys())
        assert "memory/local.md" in paths
        assert "memory/remote.md" in paths

    def test_no_sync_when_in_sync(self, sync_engine, temp_persona_dir, proxy_client):
        """Test that files already in sync don't get re-synced."""
        # Create and upload a file
        memory_dir = temp_persona_dir / "memory"
        (memory_dir / "synced.md").write_text("Synced content")

        # First sync
        plan1 = sync_engine.analyze_sync_operations()
        result1 = sync_engine.execute_sync(plan1, show_progress=False)
        assert len(result1.succeeded) == 1

        # Second sync - should have no operations
        plan2 = sync_engine.analyze_sync_operations()
        assert len(plan2.upload) == 0
        assert len(plan2.download) == 0
        assert len(plan2.conflicts) == 0
        assert plan2.total_operations == 0

    def test_detect_local_modification(
        self, sync_engine, temp_persona_dir, proxy_client
    ):
        """Test that local modifications are detected and uploaded."""
        # Create and upload a file
        memory_dir = temp_persona_dir / "memory"
        test_file = memory_dir / "modified.md"
        test_file.write_text("Original content")

        # First sync
        plan1 = sync_engine.analyze_sync_operations()
        sync_engine.execute_sync(plan1, show_progress=False)

        # Modify locally
        test_file.write_text("Modified content")

        # Second sync should detect change
        plan2 = sync_engine.analyze_sync_operations()
        assert len(plan2.upload) == 1
        assert plan2.upload[0].path == "memory/modified.md"
        assert plan2.upload[0].reason == "Local file modified"

        # Execute and verify
        result2 = sync_engine.execute_sync(plan2, show_progress=False)
        assert len(result2.succeeded) == 1

        # Verify remote has new content
        # read_blob returns: (content, md5, last_modified, content_type, version)
        content, md5, last_modified, content_type, version = proxy_client.read_blob(
            "test-persona", "memory/modified.md"
        )
        assert content == b"Modified content"

    def test_detect_remote_modification(
        self, sync_engine, temp_persona_dir, proxy_client
    ):
        """Test that remote modifications are detected and downloaded."""
        # Create and upload a file
        memory_dir = temp_persona_dir / "memory"
        test_file = memory_dir / "modified.md"
        test_file.write_text("Original content")

        # First sync
        plan1 = sync_engine.analyze_sync_operations()
        sync_engine.execute_sync(plan1, show_progress=False)

        # Modify remotely (get current version first)
        remote_index = proxy_client.get_sync_index("test-persona")
        current_version = remote_index.files["memory/modified.md"].version

        proxy_client.write_blob(
            "test-persona",
            "memory/modified.md",
            b"Remotely modified content",
            expected_version=current_version,
        )

        # Second sync should detect change
        plan2 = sync_engine.analyze_sync_operations()
        assert len(plan2.download) == 1
        assert plan2.download[0].path == "memory/modified.md"
        assert plan2.download[0].reason == "Remote file modified"

        # Execute and verify
        result2 = sync_engine.execute_sync(plan2, show_progress=False)
        assert len(result2.succeeded) == 1

        # Verify local has new content
        assert test_file.read_text() == "Remotely modified content"

    def test_detect_conflict(self, sync_engine, temp_persona_dir, proxy_client):
        """Test that conflicts are detected when both sides modify."""
        # Create and upload a file
        memory_dir = temp_persona_dir / "memory"
        test_file = memory_dir / "conflict.md"
        test_file.write_text("Original content")

        # First sync
        plan1 = sync_engine.analyze_sync_operations()
        sync_engine.execute_sync(plan1, show_progress=False)

        # Modify locally
        test_file.write_text("Local modification")

        # Modify remotely
        remote_index = proxy_client.get_sync_index("test-persona")
        current_version = remote_index.files["memory/conflict.md"].version

        proxy_client.write_blob(
            "test-persona",
            "memory/conflict.md",
            b"Remote modification",
            expected_version=current_version,
        )

        # Second sync should detect conflict
        plan2 = sync_engine.analyze_sync_operations()
        assert len(plan2.conflicts) == 1
        assert plan2.conflicts[0].path == "memory/conflict.md"
        assert plan2.conflicts[0].reason == "Both local and remote modified"

        # Execute sync - conflict should be skipped
        result2 = sync_engine.execute_sync(plan2, show_progress=False)
        assert len(result2.conflicts) == 1
        assert len(result2.succeeded) == 0

    def test_multi_file_sync(self, sync_engine, temp_persona_dir, proxy_client):
        """Test syncing multiple files at once."""
        # Create 10 local files
        memory_dir = temp_persona_dir / "memory"
        for i in range(10):
            (memory_dir / f"file{i}.md").write_text(f"Content {i}")

        # Create 5 remote files (expected_version=0 means create new)
        for i in range(10, 15):
            proxy_client.write_blob(
                "test-persona",
                f"memory/file{i}.md",
                f"Remote content {i}".encode(),
                expected_version=0,
            )

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # Should have 10 uploads and 5 downloads
        assert len(plan.upload) == 10
        assert len(plan.download) == 5
        assert plan.total_operations == 15

        # Execute sync
        result = sync_engine.execute_sync(plan, show_progress=False)

        # All should succeed
        assert len(result.succeeded) == 15
        assert len(result.failed) == 0
        assert result.success_rate == 100.0

        # Verify all 15 files exist locally
        assert len(list(memory_dir.iterdir())) == 15

        # Verify all 15 files exist remotely
        remote_index = proxy_client.get_sync_index("test-persona")
        assert len(remote_index.files) == 15

    def test_operation_logging(self, sync_engine, temp_persona_dir):
        """Test that operations are logged correctly."""
        # Create a file and sync
        memory_dir = temp_persona_dir / "memory"
        (memory_dir / "logged.md").write_text("Test")

        plan = sync_engine.analyze_sync_operations()
        sync_engine.execute_sync(plan, show_progress=False)

        # Check operation log
        recent_ops = sync_engine.operation_log.get_recent_operations(limit=10)
        assert len(recent_ops) > 0

        # Should have upload operation
        upload_ops = [op for op in recent_ops if op.op_type == "upload"]
        assert len(upload_ops) == 1
        assert upload_ops[0].path == "memory/logged.md"
        assert upload_ops[0].status == "success"

    def test_sync_with_nested_directories(
        self, sync_engine, temp_persona_dir, proxy_client
    ):
        """Test syncing files in nested directories."""
        # Create nested structure
        memory_dir = temp_persona_dir / "memory"
        nested_dir = memory_dir / "subdir" / "deep"
        nested_dir.mkdir(parents=True)
        (nested_dir / "nested_file.md").write_text("Nested content")

        # Sync
        plan = sync_engine.analyze_sync_operations()
        result = sync_engine.execute_sync(plan, show_progress=False)

        # Should succeed
        assert len(result.succeeded) == 1
        assert result.succeeded[0].path == "memory/subdir/deep/nested_file.md"

        # Verify remotely
        remote_index = proxy_client.get_sync_index("test-persona")
        paths = set(remote_index.files.keys())
        assert "memory/subdir/deep/nested_file.md" in paths

    def test_local_index_persists(self, proxy_client, temp_persona_dir):
        """Test that local index persists across SyncEngine instances."""
        from silica.developer.memory.sync import SyncEngine

        # Create first engine and sync a file
        engine1 = SyncEngine(
            client=proxy_client,
            local_base_dir=temp_persona_dir,
            namespace="test-persona",
        )

        memory_dir = temp_persona_dir / "memory"
        (memory_dir / "persistent.md").write_text("Content")

        plan1 = engine1.analyze_sync_operations()
        engine1.execute_sync(plan1, show_progress=False)

        # Create new SyncEngine instance (simulating restart)
        engine2 = SyncEngine(
            client=proxy_client,
            local_base_dir=temp_persona_dir,
            namespace="test-persona",
        )

        # Should recognize file is already synced
        plan2 = engine2.analyze_sync_operations()
        assert plan2.total_operations == 0

    def test_operation_log_persists(self, proxy_client, temp_persona_dir):
        """Test that operation log persists."""
        from silica.developer.memory.sync import SyncEngine

        # Perform sync
        engine1 = SyncEngine(
            client=proxy_client,
            local_base_dir=temp_persona_dir,
            namespace="test-persona",
        )

        memory_dir = temp_persona_dir / "memory"
        (memory_dir / "logged.md").write_text("Content")

        plan = engine1.analyze_sync_operations()
        engine1.execute_sync(plan, show_progress=False)

        # Create new SyncEngine instance
        engine2 = SyncEngine(
            client=proxy_client,
            local_base_dir=temp_persona_dir,
            namespace="test-persona",
        )

        # Should see previous operations
        ops = engine2.operation_log.get_recent_operations(limit=10)
        assert len(ops) > 0
