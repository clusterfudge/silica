"""Tests for SyncConfig dataclass and multi-namespace support."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from silica.developer.memory.sync_config import SyncConfig


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def persona_dir(temp_dir, monkeypatch):
    """Create a persona directory structure and configure personas module."""
    persona_path = temp_dir / "personas" / "test"
    persona_path.mkdir(parents=True)

    # Create memory directory
    (persona_path / "memory").mkdir()

    # Create history directory with sessions
    (persona_path / "history" / "session-1").mkdir(parents=True)
    (persona_path / "history" / "session-2").mkdir(parents=True)

    # Create persona.md
    (persona_path / "persona.md").write_text("# Test Persona")

    # Mock the personas module to use our temp directory
    from silica.developer import personas

    monkeypatch.setattr(personas, "_PERSONAS_BASE_DIRECTORY", temp_dir / "personas")

    return persona_path


class TestSyncConfig:
    """Tests for SyncConfig dataclass."""

    def test_create_basic_config(self):
        """Test creating a basic SyncConfig."""
        config = SyncConfig(
            namespace="test/namespace",
            scan_paths=[Path("/test/path")],
            index_file=Path("/test/.sync-index.json"),
            base_dir=Path("/test"),
        )

        assert config.namespace == "test/namespace"
        assert len(config.scan_paths) == 1
        assert config.scan_paths[0] == Path("/test/path")
        assert config.index_file == Path("/test/.sync-index.json")

    def test_for_memory_creates_correct_config(self, persona_dir):
        """Test SyncConfig.for_memory() creates correct configuration."""
        config = SyncConfig.for_memory("test")

        # Check namespace
        assert config.namespace == "personas/test/memory"

        # Check scan paths include memory directory and persona.md
        scan_path_names = [p.name for p in config.scan_paths]
        assert "memory" in scan_path_names
        assert "persona.md" in scan_path_names

        # Check index file location
        assert config.index_file == persona_dir / ".sync-index-memory.json"
        assert "memory" in str(config.index_file)

    def test_for_history_creates_correct_config(self, persona_dir):
        """Test SyncConfig.for_history() creates correct configuration."""
        session_id = "session-123"
        config = SyncConfig.for_history("test", session_id)

        # Check namespace includes session ID
        assert config.namespace == f"personas/test/history/{session_id}"

        # Check scan paths point to session directory
        assert len(config.scan_paths) == 1
        assert config.scan_paths[0] == persona_dir / "history" / session_id

        # Check index file is in session directory
        assert (
            config.index_file
            == persona_dir / "history" / session_id / ".sync-index-history.json"
        )
        assert session_id in str(config.index_file)

    def test_memory_and_history_configs_are_independent(self, persona_dir):
        """Test that memory and history configs don't overlap."""
        memory_config = SyncConfig.for_memory("test")
        history_config = SyncConfig.for_history("test", "session-1")

        # Different namespaces
        assert memory_config.namespace != history_config.namespace
        assert "memory" in memory_config.namespace
        assert "history" in history_config.namespace

        # Different scan paths
        assert set(memory_config.scan_paths) != set(history_config.scan_paths)

        # Different index files
        assert memory_config.index_file != history_config.index_file

    def test_multiple_history_configs_for_different_sessions(self, persona_dir):
        """Test that different session configs are independent."""
        config1 = SyncConfig.for_history("test", "session-1")
        config2 = SyncConfig.for_history("test", "session-2")

        # Different namespaces
        assert config1.namespace != config2.namespace
        assert "session-1" in config1.namespace
        assert "session-2" in config2.namespace

        # Different scan paths
        assert config1.scan_paths != config2.scan_paths

        # Different index files
        assert config1.index_file != config2.index_file
        assert "session-1" in str(config1.index_file)
        assert "session-2" in str(config2.index_file)

    def test_config_equality(self, persona_dir):
        """Test that configs with same parameters are equal."""
        config1 = SyncConfig.for_memory("test")
        config2 = SyncConfig.for_memory("test")

        assert config1.namespace == config2.namespace
        assert config1.scan_paths == config2.scan_paths
        assert config1.index_file == config2.index_file

    def test_config_with_multiple_scan_paths(self):
        """Test config with multiple scan paths."""
        config = SyncConfig(
            namespace="test/multi",
            scan_paths=[
                Path("/path1"),
                Path("/path2"),
                Path("/path3"),
            ],
            index_file=Path("/test/.sync-index.json"),
            base_dir=Path("/test"),
        )

        assert len(config.scan_paths) == 3
        assert Path("/path1") in config.scan_paths
        assert Path("/path2") in config.scan_paths
        assert Path("/path3") in config.scan_paths

    def test_memory_config_includes_persona_file(self, persona_dir):
        """Test that memory config includes persona.md file."""
        config = SyncConfig.for_memory("test")

        # Get the expected persona directory
        from silica.developer import personas

        persona = personas.get_or_create("test", interactive=False)
        persona_dir = persona.base_directory

        # persona.md should be in scan paths
        persona_file = persona_dir / "persona.md"
        assert persona_file in config.scan_paths

    def test_history_config_excludes_other_sessions(self, persona_dir):
        """Test that history config only includes specific session."""
        config = SyncConfig.for_history("test", "session-1")

        # Get the expected persona directory
        from silica.developer import personas

        persona = personas.get_or_create("test", interactive=False)
        persona_dir = persona.base_directory

        # Should only include session-1 directory
        assert len(config.scan_paths) == 1
        assert config.scan_paths[0] == persona_dir / "history" / "session-1"

        # Should not include session-2
        assert (persona_dir / "history" / "session-2") not in config.scan_paths


class TestSyncConfigCompression:
    """Tests for compression settings in SyncConfig."""

    def test_default_compression_is_false(self):
        """Test that compression defaults to False."""
        config = SyncConfig(
            namespace="test/namespace",
            scan_paths=[Path("/test/path")],
            index_file=Path("/test/.sync-index.json"),
            base_dir=Path("/test"),
        )
        assert config.compress is False

    def test_explicit_compression_setting(self):
        """Test setting compression explicitly."""
        config = SyncConfig(
            namespace="test/namespace",
            scan_paths=[Path("/test/path")],
            index_file=Path("/test/.sync-index.json"),
            base_dir=Path("/test"),
            compress=True,
        )
        assert config.compress is True

    def test_memory_config_has_compression_disabled(self, persona_dir):
        """Test that memory config has compression disabled by default."""
        config = SyncConfig.for_memory("test")
        # Memory files are small, compression not needed
        assert config.compress is False

    def test_history_config_has_compression_enabled(self, persona_dir):
        """Test that history config has compression enabled by default."""
        config = SyncConfig.for_history("test", "session-1")
        # History files can be large, compression is beneficial
        assert config.compress is True
