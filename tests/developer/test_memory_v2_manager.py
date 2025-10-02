"""
Tests for Memory V2 Manager.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch


from silica.developer.memory_v2 import MemoryManager, LocalDiskStorage


class TestMemoryManager:
    """Tests for MemoryManager class."""

    def test_init_with_default_persona(self):
        """Test initialization with default persona."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(base_path=tmpdir)

            assert manager.persona_name == "default"
            assert manager.persona_path == Path(tmpdir) / "default"
            assert manager.storage is not None
            assert isinstance(manager.storage, LocalDiskStorage)

    def test_init_with_any_persona_name(self):
        """Test initialization accepts any persona name without validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # MemoryManager should accept any string as a persona name
            manager = MemoryManager(persona_name="coding_agent", base_path=tmpdir)

            assert manager.persona_name == "coding_agent"
            assert manager.persona_path == Path(tmpdir) / "coding_agent"

    def test_init_with_nonexistent_persona_name(self):
        """Test initialization with made-up persona name (no validation)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # MemoryManager should accept any string, even if it's not a real persona
            manager = MemoryManager(
                persona_name="nonexistent_persona", base_path=tmpdir
            )

            assert manager.persona_name == "nonexistent_persona"
            assert manager.persona_path == Path(tmpdir) / "nonexistent_persona"

    def test_init_with_none_persona(self):
        """Test initialization with None persona."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(persona_name=None, base_path=tmpdir)

            assert manager.persona_name == "default"
            assert manager.persona_path == Path(tmpdir) / "default"

    def test_init_with_env_variable(self):
        """Test that MEMORY_V2_PATH environment variable is respected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MEMORY_V2_PATH": tmpdir}):
                manager = MemoryManager()

                assert str(manager.persona_path).startswith(tmpdir)
                assert manager.persona_path == Path(tmpdir) / "default"

    def test_init_with_custom_storage_backend(self):
        """Test initialization with custom storage backend."""
        mock_storage = Mock(spec=LocalDiskStorage)

        manager = MemoryManager(storage_backend=mock_storage)

        assert manager.storage is mock_storage

    def test_root_path_property(self):
        """Test root_path property returns persona_path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(persona_name="test_persona", base_path=tmpdir)

            assert manager.root_path == manager.persona_path
            assert manager.root_path == Path(tmpdir) / "test_persona"

    def test_repr(self):
        """Test string representation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(persona_name="coding_agent", base_path=tmpdir)

            repr_str = repr(manager)
            assert "MemoryManager" in repr_str
            assert "coding_agent" in repr_str
            assert tmpdir in repr_str

    def test_storage_creates_persona_directory(self):
        """Test that storage creates the persona-specific directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(persona_name="test_persona", base_path=tmpdir)

            # The directory should be created
            assert manager.persona_path.exists()
            assert manager.persona_path.is_dir()

    def test_multiple_managers_different_personas(self):
        """Test that different personas get different storage paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager1 = MemoryManager(persona_name="persona1", base_path=tmpdir)
            manager2 = MemoryManager(persona_name="persona2", base_path=tmpdir)

            assert manager1.persona_path != manager2.persona_path
            assert manager1.persona_path == Path(tmpdir) / "persona1"
            assert manager2.persona_path == Path(tmpdir) / "persona2"

    def test_persona_isolation(self):
        """Test that different personas have isolated memory storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager1 = MemoryManager(persona_name="persona1", base_path=tmpdir)
            manager2 = MemoryManager(persona_name="persona2", base_path=tmpdir)

            # Write to manager1
            manager1.storage.write("memory", "Persona 1 content")

            # Manager2 should not see it
            assert not manager2.storage.exists("memory")

            # Write to manager2
            manager2.storage.write("memory", "Persona 2 content")

            # Manager1 should still have its own content
            assert manager1.storage.read("memory") == "Persona 1 content"
            assert manager2.storage.read("memory") == "Persona 2 content"
