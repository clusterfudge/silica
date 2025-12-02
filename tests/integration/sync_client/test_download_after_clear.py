"""Test download after clearing index."""

import pytest


@pytest.mark.integration
def test_download_after_clear(memory_sync_engine, create_local_files, temp_persona_dir):
    """Test that clearing index and re-syncing downloads files (bootstrap scenario).

    This simulates a new device or fresh checkout scenario where:
    1. Files exist on remote
    2. Local index is empty (fresh start)
    3. Local filesystem is empty (or missing files)

    Expected behavior: Download files from remote (bootstrap).
    """
    # Upload a file
    create_local_files({"memory/test.md": "Test content"})

    plan = memory_sync_engine.analyze_sync_operations()
    result = memory_sync_engine.execute_sync(plan, show_progress=False)
    assert len(result.succeeded) > 0

    # Delete file locally to simulate fresh checkout
    (temp_persona_dir / "memory/test.md").unlink()

    # Clear index to simulate new device/bootstrap
    # This is the key: we need to clear AND save to persist the empty state
    memory_sync_engine.local_index._index.clear()
    memory_sync_engine.local_index._loaded = True
    memory_sync_engine.local_index.save()

    # Analyze again - should detect as bootstrap and download
    plan2 = memory_sync_engine.analyze_sync_operations()

    # Should be a download, not a delete
    assert len(plan2.download) == 1
    assert len(plan2.delete_remote) == 0
    assert plan2.download[0].path == "test.md"
    assert (
        "New remote file" in plan2.download[0].reason
        or "bootstrap" in plan2.download[0].reason.lower()
    )

    # Execute sync
    result2 = memory_sync_engine.execute_sync(plan2, show_progress=False)
    assert len(result2.succeeded) == 1

    # Verify file was downloaded
    test_file = temp_persona_dir / "memory/test.md"
    assert test_file.exists()
    assert test_file.read_text() == "Test content"
