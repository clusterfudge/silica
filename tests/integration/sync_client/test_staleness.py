"""Staleness detection integration tests (manifest-on-write)."""

import pytest


@pytest.mark.integration
@pytest.mark.memory_sync
class TestManifestOnWrite:
    """Test staleness detection via manifest-on-write feature."""

    def test_detect_other_file_changed_during_upload(
        self,
        memory_sync_engine,
        sync_client,
        create_local_files,
        temp_persona_dir,
    ):
        """Test detecting that another file changed during upload."""
        # Create and sync two files
        create_local_files(
            {
                "memory/file1.md": "File 1 original",
                "memory/file2.md": "File 2 original",
            }
        )

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Modify file1 locally
        (temp_persona_dir / "memory/file1.md").write_text("File 1 modified locally")

        # Modify file2 on remote
        index_entry = memory_sync_engine.local_index.get_entry("file2.md")
        sync_client.write_blob(
            namespace=memory_sync_engine.config.namespace,
            path="file2.md",
            content=b"File 2 modified remotely",
            expected_version=index_entry.version,
        )

        # Upload file1 - manifest should show file2 changed
        plan = memory_sync_engine.analyze_sync_operations()

        # Before upload, only file1 should be detected as needing upload
        assert len(plan.upload) == 1
        assert plan.upload[0].path == "file1.md"

        # Execute upload - manifest returned will show file2 changed
        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert result.success_rate == 100.0

        # The manifest from write_blob updated our index
        # Now analyze again - should detect file2 needs download
        plan2 = memory_sync_engine.analyze_sync_operations()

        assert len(plan2.download) == 1
        assert plan2.download[0].path == "file2.md"

        # Download file2
        result2 = memory_sync_engine.execute_sync(plan2, show_progress=False)

        assert result2.success_rate == 100.0

        # Verify file2 updated locally
        assert (
            temp_persona_dir / "memory/file2.md"
        ).read_text() == "File 2 modified remotely"

    def test_manifest_shows_all_files_after_write(
        self,
        memory_sync_engine,
        create_local_files,
    ):
        """Test that manifest after write contains all files in namespace."""
        # Create multiple files
        create_local_files(
            {
                "memory/alpha.md": "Alpha",
                "memory/beta.md": "Beta",
                "memory/gamma.md": "Gamma",
            }
        )

        # Sync all
        plan = memory_sync_engine.analyze_sync_operations()
        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert result.success_rate == 100.0

        # Verify local index has all files
        # (populated from manifests returned during upload)
        all_entries = memory_sync_engine.local_index.get_all_entries()

        assert "alpha.md" in all_entries
        assert "beta.md" in all_entries
        assert "gamma.md" in all_entries
        assert "persona.md" in all_entries

    def test_sync_when_already_in_sync(
        self,
        memory_sync_engine,
        create_local_files,
    ):
        """Test that no operations occur when already in sync."""
        # Create and sync files
        create_local_files(
            {
                "memory/file1.md": "Content 1",
                "memory/file2.md": "Content 2",
            }
        )

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Sync again immediately - should be no-op
        plan2 = memory_sync_engine.analyze_sync_operations()

        assert plan2.total_operations == 0
        assert len(plan2.upload) == 0
        assert len(plan2.download) == 0
        assert len(plan2.delete_local) == 0
        assert len(plan2.delete_remote) == 0

        # Execute anyway (should be fast)
        result = memory_sync_engine.execute_sync(plan2, show_progress=False)

        assert result.total == 0
        assert result.success_rate == 100.0

    def test_manifest_on_delete_shows_tombstone(
        self,
        memory_sync_engine,
        create_local_files,
        temp_persona_dir,
    ):
        """Test that manifest after delete shows tombstone."""
        # Create and sync file
        create_local_files({"memory/to_delete.md": "Content"})

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Delete locally
        (temp_persona_dir / "memory/to_delete.md").unlink()

        # Sync delete
        plan = memory_sync_engine.analyze_sync_operations()
        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert result.success_rate == 100.0

        # Verify local index shows tombstone
        # (from manifest returned by delete)
        entry = memory_sync_engine.local_index.get_entry("to_delete.md")

        assert entry is not None
        assert entry.is_deleted is True

        # Next sync should not try to re-delete or download
        plan2 = memory_sync_engine.analyze_sync_operations()

        assert plan2.total_operations == 0
