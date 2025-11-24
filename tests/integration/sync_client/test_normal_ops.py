"""Normal sync operations integration tests."""

import pytest


@pytest.mark.integration
@pytest.mark.memory_sync
class TestUploadOperations:
    """Test uploading files to remote."""

    def test_upload_new_memory_file(
        self, memory_sync_engine, create_local_files, temp_persona_dir
    ):
        """Test uploading a new file after initial sync."""
        # Initial sync (empty)
        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Add new file
        create_local_files({"memory/new_file.md": "New content"})

        # Sync again - should upload new file
        plan = memory_sync_engine.analyze_sync_operations()

        assert len(plan.upload) == 1
        assert plan.upload[0].path == "memory/new_file.md"

        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert len(result.succeeded) == 1
        assert result.success_rate == 100.0

        # Verify no changes on next sync
        plan2 = memory_sync_engine.analyze_sync_operations()
        assert plan2.total_operations == 0

    def test_upload_modified_memory_file(
        self, memory_sync_engine, create_local_files, temp_persona_dir
    ):
        """Test uploading a modified file."""
        # Create and sync file
        create_local_files({"memory/test.md": "Original content"})

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Modify file
        (temp_persona_dir / "memory/test.md").write_text("Modified content")

        # Sync again
        plan = memory_sync_engine.analyze_sync_operations()

        assert len(plan.upload) == 1
        assert plan.upload[0].reason == "Local file modified"

        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert len(result.succeeded) == 1

        # Verify local index updated with new version
        index_entry = memory_sync_engine.local_index.get_entry("memory/test.md")
        assert index_entry is not None
        assert index_entry.version > 1  # Version incremented

    def test_upload_persona_definition(self, memory_sync_engine, temp_persona_dir):
        """Test uploading persona.md."""
        # persona.md already exists from fixture
        # Modify it
        (temp_persona_dir / "persona.md").write_text("Updated persona definition")

        # First sync uploads it
        plan = memory_sync_engine.analyze_sync_operations()

        assert any(op.path == "persona.md" for op in plan.upload)

        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert len(result.succeeded) >= 1

        # Verify it's in the remote index
        remote_index = memory_sync_engine.client.get_sync_index(
            memory_sync_engine.config.namespace
        )

        assert "persona.md" in remote_index.files

    def test_upload_nested_directory_structure(
        self, memory_sync_engine, create_local_files
    ):
        """Test uploading nested directory structure."""
        create_local_files(
            {
                "memory/projects/project1/notes.md": "Project 1 notes",
                "memory/projects/project2/notes.md": "Project 2 notes",
                "memory/archive/old/data.md": "Archived data",
            }
        )

        plan = memory_sync_engine.analyze_sync_operations()

        # Should upload all nested files + persona.md
        assert len(plan.upload) >= 3

        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert result.success_rate == 100.0

        # Verify paths preserved in remote
        remote_index = memory_sync_engine.client.get_sync_index(
            memory_sync_engine.config.namespace
        )

        assert "memory/projects/project1/notes.md" in remote_index.files
        assert "memory/projects/project2/notes.md" in remote_index.files
        assert "memory/archive/old/data.md" in remote_index.files


@pytest.mark.integration
@pytest.mark.memory_sync
class TestDownloadOperations:
    """Test downloading files from remote."""

    def test_download_new_remote_file(
        self, memory_sync_engine, create_remote_files, temp_persona_dir
    ):
        """Test downloading a file added to remote."""
        # Initial sync
        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Add file to remote
        create_remote_files(
            "/memory",
            {"memory/remote_new.md": "Remote content"},
        )

        # Sync again - should download
        plan = memory_sync_engine.analyze_sync_operations()

        assert len(plan.download) == 1
        assert plan.download[0].path == "memory/remote_new.md"

        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert len(result.succeeded) == 1

        # Verify file downloaded
        assert (temp_persona_dir / "memory/remote_new.md").exists()
        assert (
            temp_persona_dir / "memory/remote_new.md"
        ).read_text() == "Remote content"

    def test_download_modified_remote_file(
        self,
        memory_sync_engine,
        sync_client,
        create_local_files,
        temp_persona_dir,
    ):
        """Test downloading a file modified on remote."""
        # Create and sync file
        create_local_files({"memory/sync_test.md": "Version 1"})

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Get version from index
        index_entry = memory_sync_engine.local_index.get_entry("memory/sync_test.md")
        current_version = index_entry.version

        # Modify on remote
        sync_client.write_blob(
            namespace=memory_sync_engine.config.namespace,
            path="memory/sync_test.md",
            content=b"Version 2 - remote",
            expected_version=current_version,
        )

        # Sync again
        plan = memory_sync_engine.analyze_sync_operations()

        assert len(plan.download) == 1
        assert plan.download[0].reason == "Remote file modified"

        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert len(result.succeeded) == 1

        # Verify local file updated
        assert (
            temp_persona_dir / "memory/sync_test.md"
        ).read_text() == "Version 2 - remote"

        # Verify MD5 cache updated
        from silica.developer.memory.md5_cache import MD5Cache

        cache = MD5Cache()
        cached_md5 = cache.get(temp_persona_dir / "memory/sync_test.md")
        assert cached_md5 is not None


@pytest.mark.integration
@pytest.mark.memory_sync
class TestDeleteOperations:
    """Test delete operations in both directions."""

    def test_propagate_local_deletion_to_remote(
        self, memory_sync_engine, create_local_files, temp_persona_dir
    ):
        """Test deleting a file locally propagates to remote."""
        # Create and sync file
        create_local_files({"memory/to_delete.md": "Will be deleted"})

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Delete locally
        (temp_persona_dir / "memory/to_delete.md").unlink()

        # Sync again
        plan = memory_sync_engine.analyze_sync_operations()

        assert len(plan.delete_remote) == 1
        assert plan.delete_remote[0].path == "memory/to_delete.md"
        assert plan.delete_remote[0].reason == "Deleted locally"

        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert len(result.succeeded) == 1

        # Verify tombstone created on remote
        remote_index = memory_sync_engine.client.get_sync_index(
            memory_sync_engine.config.namespace
        )

        assert "memory/to_delete.md" in remote_index.files
        assert remote_index.files["memory/to_delete.md"].is_deleted is True

        # Next sync should not re-download
        plan2 = memory_sync_engine.analyze_sync_operations()
        assert plan2.total_operations == 0

    def test_honor_remote_tombstone(
        self,
        memory_sync_engine,
        sync_client,
        create_local_files,
        temp_persona_dir,
    ):
        """Test that remote tombstone deletes local file."""
        # Create and sync file
        create_local_files({"memory/remote_deleted.md": "Content"})

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Get version and delete on remote
        index_entry = memory_sync_engine.local_index.get_entry(
            "memory/remote_deleted.md"
        )
        current_version = index_entry.version

        sync_client.delete_blob(
            namespace=memory_sync_engine.config.namespace,
            path="memory/remote_deleted.md",
            expected_version=current_version,
        )

        # Sync again
        plan = memory_sync_engine.analyze_sync_operations()

        assert len(plan.delete_local) == 1
        assert plan.delete_local[0].reason == "Explicit remote deletion (tombstone)"

        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert len(result.succeeded) == 1

        # Verify file deleted locally
        assert not (temp_persona_dir / "memory/remote_deleted.md").exists()

        # Verify index tracks tombstone
        index_entry = memory_sync_engine.local_index.get_entry(
            "memory/remote_deleted.md"
        )
        assert index_entry.is_deleted is True

    def test_delete_multiple_files(
        self, memory_sync_engine, create_local_files, temp_persona_dir
    ):
        """Test deleting multiple files in one sync."""
        # Create and sync files
        create_local_files(
            {
                "memory/delete1.md": "File 1",
                "memory/delete2.md": "File 2",
                "memory/delete3.md": "File 3",
            }
        )

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Delete all three
        (temp_persona_dir / "memory/delete1.md").unlink()
        (temp_persona_dir / "memory/delete2.md").unlink()
        (temp_persona_dir / "memory/delete3.md").unlink()

        # Sync again
        plan = memory_sync_engine.analyze_sync_operations()

        assert len(plan.delete_remote) == 3

        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert len(result.succeeded) == 3
        assert result.success_rate == 100.0

        # Verify all tombstoned
        remote_index = memory_sync_engine.client.get_sync_index(
            memory_sync_engine.config.namespace
        )

        for i in range(1, 4):
            path = f"memory/delete{i}.md"
            assert path in remote_index.files
            assert remote_index.files[path].is_deleted is True
