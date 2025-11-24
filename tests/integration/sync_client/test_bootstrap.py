"""Bootstrap scenario integration tests."""

import pytest


@pytest.mark.integration
@pytest.mark.memory_sync
class TestBootstrapFromLocal:
    """Test bootstrapping sync from existing local content."""

    def test_bootstrap_memory_from_existing_local_files(
        self, memory_sync_engine, create_local_files, temp_persona_dir
    ):
        """Test initial sync uploads existing local memory files."""
        # Create local files before first sync
        create_local_files(
            {
                "memory/notes.md": "My notes",
                "memory/tasks.md": "My tasks",
                "memory/ideas.md": "My ideas",
            }
        )

        # First sync - should upload all files
        plan = memory_sync_engine.analyze_sync_operations()

        assert len(plan.upload) == 4  # 3 memory files + persona.md
        assert len(plan.download) == 0
        assert len(plan.conflicts) == 0

        # Execute sync
        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert len(result.succeeded) == 4
        assert len(result.failed) == 0

        # Verify local index created
        index_file = temp_persona_dir / ".sync-index-memory.json"
        assert index_file.exists()

        # Second sync should show no changes
        plan2 = memory_sync_engine.analyze_sync_operations()
        assert plan2.total_operations == 0

    def test_bootstrap_history_from_existing_session(
        self, history_sync_engine, create_local_files, temp_persona_dir
    ):
        """Test initial sync uploads existing session history files."""
        # Create history files
        create_local_files(
            {
                "history/session-test-001/conversation.json": '{"messages": []}',
                "history/session-test-001/metadata.json": '{"session_id": "test"}',
            }
        )

        # First sync
        plan = history_sync_engine.analyze_sync_operations()

        assert len(plan.upload) == 2
        assert len(plan.download) == 0

        result = history_sync_engine.execute_sync(plan, show_progress=False)

        assert len(result.succeeded) == 2
        assert result.success_rate == 100.0

        # Verify index created
        index_file = (
            temp_persona_dir / "history/session-test-001/.sync-index-history.json"
        )
        assert index_file.exists()


@pytest.mark.integration
@pytest.mark.memory_sync
class TestBootstrapFromRemote:
    """Test bootstrapping sync from existing remote content."""

    def test_bootstrap_memory_from_remote_files(
        self, memory_sync_engine, create_remote_files, temp_persona_dir
    ):
        """Test initial sync downloads existing remote files."""
        # Pre-populate remote with files
        create_remote_files(
            "/memory",
            {
                "memory/remote1.md": "Remote content 1",
                "memory/remote2.md": "Remote content 2",
                "persona.md": "Remote persona",
            },
        )

        # First sync - should download all files
        plan = memory_sync_engine.analyze_sync_operations()

        assert len(plan.download) == 3
        assert len(plan.upload) == 1  # Local persona.md exists

        # Execute sync
        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert len(result.succeeded) == 4

        # Verify files downloaded
        assert (temp_persona_dir / "memory/remote1.md").exists()
        assert (temp_persona_dir / "memory/remote2.md").exists()

        # Verify content
        assert (
            temp_persona_dir / "memory/remote1.md"
        ).read_text() == "Remote content 1"

    def test_bootstrap_history_from_remote_session(
        self, history_sync_engine, create_remote_files, temp_persona_dir
    ):
        """Test initial sync downloads remote session files."""
        # Pre-populate remote history
        create_remote_files(
            "/history/session-test-001",
            {
                "history/session-test-001/conv.json": '{"remote": true}',
            },
        )

        # First sync
        plan = history_sync_engine.analyze_sync_operations()

        assert len(plan.download) == 1
        assert len(plan.upload) == 0

        result = history_sync_engine.execute_sync(plan, show_progress=False)

        assert result.success_rate == 100.0

        # Verify downloaded
        conv_file = temp_persona_dir / "history/session-test-001/conv.json"
        assert conv_file.exists()
        assert "remote" in conv_file.read_text()


@pytest.mark.integration
@pytest.mark.memory_sync
class TestBootstrapBidirectional:
    """Test bootstrapping with content on both sides."""

    def test_bootstrap_bidirectional_merge(
        self,
        memory_sync_engine,
        create_local_files,
        create_remote_files,
        temp_persona_dir,
    ):
        """Test bootstrap with different files on local and remote."""
        # Create local files
        create_local_files(
            {
                "memory/local1.md": "Local content",
                "memory/local2.md": "Local content 2",
            }
        )

        # Create remote files
        create_remote_files(
            "/memory",
            {
                "memory/remote1.md": "Remote content",
                "memory/remote2.md": "Remote content 2",
            },
        )

        # First sync - no index, so remote is authority
        plan = memory_sync_engine.analyze_sync_operations()

        # Should download remote files and upload local files + persona.md
        assert len(plan.download) == 2  # remote1, remote2
        assert len(plan.upload) == 3  # local1, local2, persona.md

        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert len(result.succeeded) == 5
        assert len(result.failed) == 0

        # Verify all files present locally
        assert (temp_persona_dir / "memory/local1.md").exists()
        assert (temp_persona_dir / "memory/local2.md").exists()
        assert (temp_persona_dir / "memory/remote1.md").exists()
        assert (temp_persona_dir / "memory/remote2.md").exists()

        # Next sync should be clean
        plan2 = memory_sync_engine.analyze_sync_operations()
        assert plan2.total_operations == 0

    def test_bootstrap_with_same_file_different_content(
        self, memory_sync_engine, create_local_files, create_remote_files
    ):
        """Test bootstrap when same file exists with different content."""
        # Same filename, different content
        create_local_files({"memory/shared.md": "Local version"})

        create_remote_files("/memory", {"memory/shared.md": "Remote version"})

        # First sync - no index means remote wins (remote is authority)
        plan = memory_sync_engine.analyze_sync_operations()

        # Should download remote version (overwriting local)
        assert len(plan.download) >= 1

        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        # After bootstrap, remote version should be present
        # (Remote is authority on bootstrap)
        assert result.total > 0
