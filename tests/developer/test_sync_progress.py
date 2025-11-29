"""Test sync progress bar functionality."""

from unittest.mock import Mock, patch, MagicMock

import pytest

from silica.developer.memory.sync import SyncEngine, SyncPlan, SyncOperationDetail
from silica.developer.memory.proxy_client import MemoryProxyClient


@pytest.fixture
def mock_client():
    """Mock memory proxy client."""
    client = Mock(spec=MemoryProxyClient)
    client.get_sync_index.return_value = {"files": {}, "version": 1}
    return client


@pytest.fixture
def sync_engine(tmp_path, mock_client):
    """Create a sync engine for testing."""
    from silica.developer.memory.sync_config import SyncConfig

    config = SyncConfig(
        namespace="test",
        scan_paths=[tmp_path],
        index_file=tmp_path / ".sync-index.json",
        base_dir=tmp_path,
    )
    engine = SyncEngine(
        client=mock_client,
        config=config,
    )
    return engine


def test_execute_sync_with_progress(sync_engine, mock_client):
    """Test that execute_sync shows progress bar when show_progress=True."""
    # Create a plan with some operations
    plan = SyncPlan()
    plan.upload.append(
        SyncOperationDetail(
            type="upload",
            path="test.md",
            reason="new file",
            local_md5="abc123",
            remote_md5=None,
        )
    )

    # Mock the upload method
    sync_engine.upload_file = Mock(return_value=True)

    # Mock Progress to verify it's used
    with patch("rich.progress.Progress") as MockProgress:
        mock_progress = MagicMock()
        MockProgress.return_value = mock_progress
        mock_progress.add_task.return_value = "task_id"

        # Execute sync with progress
        result = sync_engine.execute_sync(plan, show_progress=True)

        # Verify Progress was created and used
        MockProgress.assert_called_once()
        mock_progress.start.assert_called_once()
        mock_progress.add_task.assert_called_once()
        mock_progress.update.assert_called()
        mock_progress.stop.assert_called_once()

        # Verify the operation succeeded
        assert len(result.succeeded) == 1
        assert len(result.failed) == 0


def test_execute_sync_without_progress(sync_engine):
    """Test that execute_sync works without progress bar."""
    # Create a plan with some operations
    plan = SyncPlan()
    plan.upload.append(
        SyncOperationDetail(
            type="upload",
            path="test.md",
            reason="new file",
            local_md5="abc123",
            remote_md5=None,
        )
    )

    # Mock the upload method
    sync_engine.upload_file = Mock(return_value=True)

    # Execute sync without progress
    result = sync_engine.execute_sync(plan, show_progress=False)

    # Verify the operation succeeded (no progress bar, but still works)
    assert len(result.succeeded) == 1
    assert len(result.failed) == 0


def test_execute_sync_with_multiple_operations(sync_engine):
    """Test progress bar with multiple operations."""
    # Create a plan with multiple operations
    plan = SyncPlan()
    for i in range(5):
        plan.upload.append(
            SyncOperationDetail(
                type="upload",
                path=f"test{i}.md",
                reason="new file",
                local_md5=f"abc{i}",
                remote_md5=None,
            )
        )

    # Mock the upload method
    sync_engine.upload_file = Mock(return_value=True)

    # Mock Progress to verify it's called correctly
    with patch("rich.progress.Progress") as MockProgress:
        mock_progress = MagicMock()
        MockProgress.return_value = mock_progress
        mock_progress.add_task.return_value = "task_id"

        # Execute sync
        result = sync_engine.execute_sync(plan, show_progress=True)

        # Verify progress was updated for each operation
        assert mock_progress.update.call_count == 5
        assert len(result.succeeded) == 5


def test_execute_sync_progress_with_failures(sync_engine):
    """Test that progress bar continues even with failures."""
    # Create a plan with operations
    plan = SyncPlan()
    plan.upload.append(
        SyncOperationDetail(
            type="upload",
            path="test1.md",
            reason="new file",
            local_md5="abc1",
            remote_md5=None,
        )
    )
    plan.upload.append(
        SyncOperationDetail(
            type="upload",
            path="test2.md",
            reason="new file",
            local_md5="abc2",
            remote_md5=None,
        )
    )

    # Mock upload - first succeeds, second fails
    sync_engine.upload_file = Mock(side_effect=[True, Exception("Network error")])

    with patch("rich.progress.Progress") as MockProgress:
        mock_progress = MagicMock()
        MockProgress.return_value = mock_progress
        mock_progress.add_task.return_value = "task_id"

        # Execute sync
        result = sync_engine.execute_sync(plan, show_progress=True)

        # Verify progress was updated for both operations
        assert mock_progress.update.call_count == 2
        assert len(result.succeeded) == 1
        assert len(result.failed) == 1

        # Verify progress bar was stopped
        mock_progress.stop.assert_called_once()
