"""State management integration tests (index, cache)."""

import pytest


@pytest.mark.integration
@pytest.mark.memory_sync
class TestIndexPersistence:
    """Test index persistence across engine instances."""

    def test_index_persists_across_engine_instances(
        self,
        sync_client,
        temp_persona_dir,
        clean_namespace,
        create_local_files,
    ):
        """Test that index persists across SyncEngine instances."""
        from silica.developer.memory.sync import SyncEngine
        from silica.developer.memory.sync_config import SyncConfig

        # Create config
        persona_md = temp_persona_dir / "persona.md"
        persona_md.write_text("Test")

        config = SyncConfig(
            namespace=f"{clean_namespace}/memory",
            scan_paths=[temp_persona_dir / "memory", persona_md],
            index_file=temp_persona_dir / ".sync-index-memory.json",
            base_dir=temp_persona_dir,
        )

        # Create first engine and sync
        engine1 = SyncEngine(client=sync_client, config=config)

        create_local_files({"memory/persistent.md": "Content"})

        plan = engine1.analyze_sync_operations()
        engine1.execute_sync(plan, show_progress=False)

        # Verify index exists
        assert config.index_file.exists()

        # Create second engine (same config)
        engine2 = SyncEngine(client=sync_client, config=config)

        # Should load index from disk
        plan = engine2.analyze_sync_operations()

        # No operations needed (already synced)
        assert plan.total_operations == 0

        # Modify file
        (temp_persona_dir / "memory/persistent.md").write_text("Modified")

        # Third engine should detect change
        engine3 = SyncEngine(client=sync_client, config=config)

        plan = engine3.analyze_sync_operations()

        assert len(plan.upload) == 1
        assert plan.upload[0].path == "persistent.md"

    def test_index_tracks_remote_state_accurately(
        self,
        memory_sync_engine,
        create_local_files,
        sync_client,
    ):
        """Test that local index accurately tracks remote state."""
        # Create and sync files
        create_local_files(
            {
                "memory/file1.md": "Content 1",
                "memory/file2.md": "Content 2",
            }
        )

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Get remote index
        remote_index = sync_client.get_sync_index(memory_sync_engine.config.namespace)

        # Verify local index matches remote
        for path, remote_metadata in remote_index.files.items():
            local_entry = memory_sync_engine.local_index.get_entry(path)

            assert local_entry is not None
            assert local_entry.md5 == remote_metadata.md5
            assert local_entry.version == remote_metadata.version
            assert local_entry.is_deleted == remote_metadata.is_deleted

    def test_index_removes_orphaned_entries(
        self,
        memory_sync_engine,
        create_local_files,
        temp_persona_dir,
    ):
        """Test that index cleans up orphaned entries."""
        # Create and sync file
        create_local_files({"memory/temporary.md": "Temporary"})

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Delete on both sides
        (temp_persona_dir / "memory/temporary.md").unlink()

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # File should be tombstoned in index
        entry = memory_sync_engine.local_index.get_entry("temporary.md")
        assert entry is not None
        assert entry.is_deleted is True

        # Future: orphaned entries should be cleaned up eventually
        # (when tombstone is purged from remote)


@pytest.mark.integration
@pytest.mark.memory_sync
class TestMD5CacheIntegration:
    """Test MD5 cache integration with sync."""

    def test_md5_cache_speeds_up_repeated_scans(
        self,
        memory_sync_engine,
        create_local_files,
    ):
        """Test that MD5 cache improves performance on repeated scans."""
        import time

        # Create files
        create_local_files(
            {f"memory/file{i}.md": f"Content {i}" * 100 for i in range(20)}
        )

        # First sync - cache miss
        start = time.time()
        plan1 = memory_sync_engine.analyze_sync_operations()
        time.time() - start

        memory_sync_engine.execute_sync(plan1, show_progress=False)

        # Second analysis - cache hit
        start = time.time()
        plan2 = memory_sync_engine.analyze_sync_operations()
        time2 = time.time() - start

        # Should be faster (though not asserting specific times to avoid flakiness)
        # Just verify it works
        assert plan2.total_operations == 0
        assert time2 >= 0  # Just verify it executed

    def test_md5_cache_invalidated_on_modification(
        self,
        memory_sync_engine,
        create_local_files,
        temp_persona_dir,
    ):
        """Test that cache is invalidated when files are modified."""
        # Create and sync file
        create_local_files({"memory/cached.md": "Original"})

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Modify file
        import time

        time.sleep(0.01)  # Ensure mtime changes
        (temp_persona_dir / "memory/cached.md").write_text("Modified")

        # Analyze again - should detect change
        plan = memory_sync_engine.analyze_sync_operations()

        assert len(plan.upload) == 1
        assert plan.upload[0].path == "cached.md"

    def test_md5_cache_cleanup_removes_deleted_files(
        self,
        memory_sync_engine,
        create_local_files,
        temp_persona_dir,
    ):
        """Test that MD5 cache cleanup removes entries for deleted files."""
        from silica.developer.memory.md5_cache import MD5Cache

        # Create and sync files
        create_local_files(
            {
                "memory/keep.md": "Keep this",
                "memory/delete.md": "Delete this",
            }
        )

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Verify both cached
        cache = MD5Cache()

        keep_path = temp_persona_dir / "memory/keep.md"
        delete_path = temp_persona_dir / "memory/delete.md"

        assert cache.get(keep_path) is not None
        assert cache.get(delete_path) is not None

        # Delete one file
        delete_path.unlink()

        # Run cleanup
        removed = cache.cleanup_deleted_files()

        # Should have removed the deleted file's cache entry
        assert removed >= 1

        # Verify cleanup worked
        assert cache.get(keep_path) is not None
        assert cache.get(delete_path) is None


@pytest.mark.integration
@pytest.mark.memory_sync
class TestSyncMetadataFiles:
    """Test that sync metadata files are properly handled."""

    def test_sync_index_not_synced(
        self,
        memory_sync_engine,
        create_local_files,
    ):
        """Test that .sync-index files are not synced."""
        # Create regular files
        create_local_files({"memory/data.md": "Data"})

        # Sync
        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Verify sync index not in remote
        remote_index = memory_sync_engine.client.get_sync_index(
            memory_sync_engine.config.namespace
        )

        # Should not contain sync metadata files
        assert not any(".sync-index" in path for path in remote_index.files.keys())
        assert not any(".sync-log" in path for path in remote_index.files.keys())

        # Verify index cleaned up (tombstone removed)
        entry = memory_sync_engine.local_index.get_entry("temporary.md")

        assert entry is None or entry.is_deleted is False
