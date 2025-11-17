"""Tests for multi-namespace sync support.

These tests verify that multiple SyncEngine instances with different configs
can operate independently without interfering with each other.
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from silica.developer.memory.sync import SyncEngine
from silica.developer.memory.sync_config import SyncConfig
from silica.developer.memory.proxy_client import (
    FileMetadata,
    MemoryProxyClient,
    SyncIndexResponse,
)


def make_sync_index_response(files_list):
    """Helper to create SyncIndexResponse from list of file dicts."""
    files_dict = {}
    for file_dict in files_list:
        path = file_dict["path"]
        files_dict[path] = FileMetadata(
            md5=file_dict["md5"],
            last_modified=datetime.fromisoformat(file_dict["last_modified"]),
            size=file_dict["size"],
            version=file_dict["version"],
            is_deleted=file_dict.get("is_deleted", False),
        )

    return SyncIndexResponse(
        files=files_dict,
        index_last_modified=datetime.now(timezone.utc),
        index_version=max((f.version for f in files_dict.values()), default=0),
    )


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def persona_dir(temp_dir):
    """Create a persona directory structure."""
    persona_path = temp_dir / "personas" / "default"
    persona_path.mkdir(parents=True)

    # Create memory directory with files
    memory_dir = persona_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "note1.md").write_text("memory note 1")
    (memory_dir / "note2.md").write_text("memory note 2")

    # Create persona.md
    (persona_path / "persona.md").write_text("# Test Persona")

    # Create history directories with session files
    session1_dir = persona_path / "history" / "session-1"
    session1_dir.mkdir(parents=True)
    (session1_dir / "001_user.md").write_text("user message 1")
    (session1_dir / "002_assistant.md").write_text("assistant response 1")

    session2_dir = persona_path / "history" / "session-2"
    session2_dir.mkdir(parents=True)
    (session2_dir / "001_user.md").write_text("user message 2")
    (session2_dir / "002_assistant.md").write_text("assistant response 2")

    return persona_path


@pytest.fixture
def mock_client():
    """Create a mock MemoryProxyClient."""
    return MagicMock(spec=MemoryProxyClient)


class TestMultiNamespaceIndependence:
    """Test that multiple sync engines operate independently."""

    def test_memory_engine_creation_with_config(self, mock_client, persona_dir):
        """Test creating a sync engine with memory config."""
        config = SyncConfig.for_memory("default", persona_dir)
        engine = SyncEngine(client=mock_client, config=config)

        assert engine.config == config
        assert engine.config.namespace == "personas/default/memory"
        assert engine.local_index.index_file == config.index_file

    def test_history_engine_creation_with_config(self, mock_client, persona_dir):
        """Test creating a sync engine with history config."""
        config = SyncConfig.for_history("default", persona_dir, "session-1")
        engine = SyncEngine(client=mock_client, config=config)

        assert engine.config == config
        assert engine.config.namespace == "personas/default/history/session-1"
        assert engine.local_index.index_file == config.index_file

    def test_memory_and_history_engines_have_different_indices(
        self, mock_client, persona_dir
    ):
        """Test that memory and history engines use different index files."""
        memory_config = SyncConfig.for_memory("default", persona_dir)
        history_config = SyncConfig.for_history("default", persona_dir, "session-1")

        memory_engine = SyncEngine(client=mock_client, config=memory_config)
        history_engine = SyncEngine(client=mock_client, config=history_config)

        # Different index files
        assert (
            memory_engine.local_index.index_file
            != history_engine.local_index.index_file
        )

        # Indices are independent
        memory_engine.local_index.update_entry(
            "test.md",
            FileMetadata(
                md5="test_md5",
                last_modified=datetime.now(timezone.utc),
                size=100,
                version=1000,
                is_deleted=False,
            ),
        )

        # History engine should not see this entry
        assert history_engine.local_index.get_entry("test.md") is None

    def test_memory_engine_scans_only_memory_files(self, mock_client, persona_dir):
        """Test that memory engine only scans memory files and persona.md."""
        config = SyncConfig.for_memory("default", persona_dir)
        engine = SyncEngine(client=mock_client, config=config)

        # Configure mock to return empty remote
        mock_client.get_sync_index.return_value = make_sync_index_response([])

        # Analyze sync
        plan = engine.analyze_sync_operations()

        # Should include memory files and persona.md
        upload_paths = {op.path for op in plan.upload}
        assert "memory/note1.md" in upload_paths
        assert "memory/note2.md" in upload_paths
        assert "persona.md" in upload_paths

        # Should NOT include history files
        assert not any("history" in path for path in upload_paths)
        assert not any("session" in path for path in upload_paths)

    def test_history_engine_scans_only_session_files(self, mock_client, persona_dir):
        """Test that history engine only scans files for its session."""
        config = SyncConfig.for_history("default", persona_dir, "session-1")
        engine = SyncEngine(client=mock_client, config=config)

        # Configure mock to return empty remote
        mock_client.get_sync_index.return_value = make_sync_index_response([])

        # Analyze sync
        plan = engine.analyze_sync_operations()

        # Should include session-1 files (relative to history/)
        upload_paths = {op.path for op in plan.upload}
        assert "session-1/001_user.md" in upload_paths
        assert "session-1/002_assistant.md" in upload_paths

        # Should NOT include session-2 files
        assert not any("session-2" in path for path in upload_paths)

        # Should NOT include memory files or persona.md
        assert not any("memory" in path for path in upload_paths)
        assert "persona.md" not in upload_paths

    def test_multiple_history_engines_for_different_sessions(
        self, mock_client, persona_dir
    ):
        """Test that history engines for different sessions are independent."""
        config1 = SyncConfig.for_history("default", persona_dir, "session-1")
        config2 = SyncConfig.for_history("default", persona_dir, "session-2")

        engine1 = SyncEngine(client=mock_client, config=config1)
        engine2 = SyncEngine(client=mock_client, config=config2)

        # Different namespaces
        assert engine1.config.namespace != engine2.config.namespace

        # Different index files
        assert engine1.local_index.index_file != engine2.local_index.index_file

        # Configure mocks
        mock_client.get_sync_index.return_value = make_sync_index_response([])

        # Analyze sync for session-1
        plan1 = engine1.analyze_sync_operations()
        upload_paths1 = {op.path for op in plan1.upload}

        # Analyze sync for session-2
        plan2 = engine2.analyze_sync_operations()
        upload_paths2 = {op.path for op in plan2.upload}

        # session-1 should only see session-1 files
        assert "session-1/001_user.md" in upload_paths1
        assert not any("session-2" in path for path in upload_paths1)

        # session-2 should only see session-2 files
        assert "session-2/001_user.md" in upload_paths2
        assert not any("session-1" in path for path in upload_paths2)

    def test_engines_use_independent_indices(self, mock_client, persona_dir):
        """Test that different engines use independent indices (no shared state)."""
        memory_config = SyncConfig.for_memory("default", persona_dir)
        history_config = SyncConfig.for_history("default", persona_dir, "session-1")

        memory_engine = SyncEngine(client=mock_client, config=memory_config)
        history_engine = SyncEngine(client=mock_client, config=history_config)

        # Different index files
        assert (
            memory_engine.local_index.index_file
            != history_engine.local_index.index_file
        )

        # Update in memory engine
        memory_engine.local_index.update_entry(
            "memory/test.md",
            FileMetadata(
                md5="test_md5",
                last_modified=datetime.now(timezone.utc),
                size=100,
                version=1000,
                is_deleted=False,
            ),
        )

        # History engine should not see this entry
        assert history_engine.local_index.get_entry("memory/test.md") is None

    def test_concurrent_sync_operations_dont_interfere(self, mock_client, persona_dir):
        """Test that syncing different namespaces doesn't cause conflicts."""
        memory_config = SyncConfig.for_memory("default", persona_dir)
        history_config = SyncConfig.for_history("default", persona_dir, "session-1")

        memory_engine = SyncEngine(client=mock_client, config=memory_config)
        history_engine = SyncEngine(client=mock_client, config=history_config)

        # Configure mocks to return empty remote
        mock_client.get_sync_index.return_value = make_sync_index_response([])

        # Analyze both (simulating concurrent operations)
        memory_plan = memory_engine.analyze_sync_operations()
        history_plan = history_engine.analyze_sync_operations()

        # Both should have operations
        assert memory_plan.total_operations > 0
        assert history_plan.total_operations > 0

        # Plans should be completely independent
        memory_paths = {op.path for op in memory_plan.upload}
        history_paths = {op.path for op in history_plan.upload}

        # No overlap
        assert len(memory_paths & history_paths) == 0

    def test_index_persistence_per_namespace(self, mock_client, persona_dir):
        """Test that index changes persist per namespace."""
        memory_config = SyncConfig.for_memory("default", persona_dir)
        history_config = SyncConfig.for_history("default", persona_dir, "session-1")

        # Create engines and update indices
        memory_engine = SyncEngine(client=mock_client, config=memory_config)
        memory_engine.local_index.update_entry(
            "memory/note.md",
            FileMetadata(
                md5="memory_md5",
                last_modified=datetime.now(timezone.utc),
                size=100,
                version=1000,
                is_deleted=False,
            ),
        )
        memory_engine.local_index.save()

        history_engine = SyncEngine(client=mock_client, config=history_config)
        history_engine.local_index.update_entry(
            "history/session-1/msg.md",
            FileMetadata(
                md5="history_md5",
                last_modified=datetime.now(timezone.utc),
                size=200,
                version=2000,
                is_deleted=False,
            ),
        )
        history_engine.local_index.save()

        # Create new engines (simulating restart)
        new_memory_engine = SyncEngine(client=mock_client, config=memory_config)
        new_history_engine = SyncEngine(client=mock_client, config=history_config)

        # Load indices
        new_memory_engine.local_index.load()
        new_history_engine.local_index.load()

        # Memory index should have memory entry only
        memory_entry = new_memory_engine.local_index.get_entry("memory/note.md")
        assert memory_entry is not None
        assert memory_entry.md5 == "memory_md5"

        history_entry_in_memory = new_memory_engine.local_index.get_entry(
            "history/session-1/msg.md"
        )
        assert history_entry_in_memory is None

        # History index should have history entry only
        history_entry = new_history_engine.local_index.get_entry(
            "history/session-1/msg.md"
        )
        assert history_entry is not None
        assert history_entry.md5 == "history_md5"

        memory_entry_in_history = new_history_engine.local_index.get_entry(
            "memory/note.md"
        )
        assert memory_entry_in_history is None


class TestBackwardsCompatibility:
    """Test backwards compatibility with old constructor."""

    def test_old_constructor_still_works(self, mock_client, temp_dir):
        """Test that old constructor signature still works (for now)."""
        # This should work with deprecation
        # Note: We'll implement this after the main refactoring
        pass  # TODO: Implement deprecation path
