"""Memory-specific sync integration tests."""

import pytest


@pytest.mark.integration
@pytest.mark.memory_sync
class TestMemorySyncSpecific:
    """Memory sync specific scenarios."""

    def test_sync_memory_directory_structure(
        self, memory_sync_engine, create_local_files, temp_persona_dir
    ):
        """Test that memory directory structure is preserved."""
        # Create nested structure
        create_local_files(
            {
                "memory/projects/alpha/notes.md": "Alpha notes",
                "memory/projects/alpha/tasks.md": "Alpha tasks",
                "memory/projects/beta/notes.md": "Beta notes",
                "memory/reference/docs/guide.md": "Guide",
                "memory/reference/docs/api.md": "API",
            }
        )

        # Sync
        plan = memory_sync_engine.analyze_sync_operations()
        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert result.success_rate == 100.0

        # Verify remote structure matches
        remote_index = memory_sync_engine.client.get_sync_index(
            memory_sync_engine.config.namespace
        )

        expected_paths = [
            "memory/projects/alpha/notes.md",
            "memory/projects/alpha/tasks.md",
            "memory/projects/beta/notes.md",
            "memory/reference/docs/guide.md",
            "memory/reference/docs/api.md",
            "persona.md",
        ]

        for path in expected_paths:
            assert path in remote_index.files

        # Clean environment and download
        for file in temp_persona_dir.rglob("*.md"):
            if file.name != "persona.md":
                file.unlink()

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Verify directory structure recreated
        assert (temp_persona_dir / "memory/projects/alpha/notes.md").exists()
        assert (temp_persona_dir / "memory/projects/beta/notes.md").exists()
        assert (temp_persona_dir / "memory/reference/docs/guide.md").exists()

    def test_memory_excludes_history_files(
        self, memory_sync_engine, create_local_files, temp_persona_dir
    ):
        """Test that memory sync ignores history files."""
        # Create both memory and history files
        create_local_files(
            {
                "memory/mem_file.md": "Memory content",
                "history/session-001/conv.json": '{"session": "data"}',
                "history/session-002/conv.json": '{"session": "data"}',
            }
        )

        # Sync memory
        plan = memory_sync_engine.analyze_sync_operations()

        # Should only see memory files + persona.md, not history
        uploaded_paths = [op.path for op in plan.upload]

        assert "memory/mem_file.md" in uploaded_paths
        assert "persona.md" in uploaded_paths
        assert not any("history" in path for path in uploaded_paths)

        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Verify remote only has memory files
        remote_index = memory_sync_engine.client.get_sync_index(
            memory_sync_engine.config.namespace
        )

        assert "memory/mem_file.md" in remote_index.files
        assert not any("history" in path for path in remote_index.files.keys())

    def test_persona_md_included_in_memory_sync(
        self, memory_sync_engine, temp_persona_dir
    ):
        """Test that persona.md is included in memory sync."""
        # Modify persona.md
        (temp_persona_dir / "persona.md").write_text(
            """# Test Persona
            
Role: Testing agent
Skills: Integration testing
"""
        )

        # Sync
        plan = memory_sync_engine.analyze_sync_operations()

        assert any(op.path == "persona.md" for op in plan.upload)

        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Verify persona.md on remote
        remote_index = memory_sync_engine.client.get_sync_index(
            memory_sync_engine.config.namespace
        )

        assert "persona.md" in remote_index.files

        # Download to clean environment
        (temp_persona_dir / "persona.md").unlink()

        plan = memory_sync_engine.analyze_sync_operations()
        memory_sync_engine.execute_sync(plan, show_progress=False)

        # Verify downloaded
        assert (temp_persona_dir / "persona.md").exists()
        assert "Test Persona" in (temp_persona_dir / "persona.md").read_text()

    def test_memory_sync_with_empty_subdirectories(
        self, memory_sync_engine, create_local_files, temp_persona_dir
    ):
        """Test that empty subdirectories don't cause issues."""
        # Create some files and empty directories
        create_local_files(
            {
                "memory/active/file1.md": "Content 1",
                "memory/active/file2.md": "Content 2",
            }
        )

        # Create empty directory
        (temp_persona_dir / "memory/empty").mkdir()
        (temp_persona_dir / "memory/also_empty/nested").mkdir(parents=True)

        # Sync - should only sync files
        plan = memory_sync_engine.analyze_sync_operations()
        result = memory_sync_engine.execute_sync(plan, show_progress=False)

        assert result.success_rate == 100.0

        # Only files should be in remote index (directories aren't tracked)
        remote_index = memory_sync_engine.client.get_sync_index(
            memory_sync_engine.config.namespace
        )

        assert "memory/active/file1.md" in remote_index.files
        assert "memory/active/file2.md" in remote_index.files
