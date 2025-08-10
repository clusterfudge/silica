"""Tests for the memory webapp module."""

import pytest
from unittest.mock import patch

from silica.developer.web.app import MemoryWebApp, run_memory_webapp
from silica.developer.memory import MemoryManager


class TestMemoryWebApp:
    """Test the MemoryWebApp class."""

    @pytest.fixture
    def memory_manager(self, tmp_path):
        """Create a memory manager with a temporary directory."""
        mm = MemoryManager(tmp_path)
        # Create some test memory entries
        mm.write_entry("test1", "# Test 1\n\nThis is a test entry.")
        mm.write_entry("test2", "# Test 2\n\nThis is another test entry.")
        mm.write_entry("folder/nested", "# Nested\n\nThis is a nested entry.")
        return mm

    @pytest.fixture
    def webapp(self, memory_manager):
        """Create a memory webapp with the test memory manager."""
        app = MemoryWebApp(memory_manager)
        app.app.config["TESTING"] = True
        app.app.config["SERVER_NAME"] = "localhost"
        app.app.config["APPLICATION_ROOT"] = "/"
        app.app.config["PREFERRED_URL_SCHEME"] = "http"
        return app

    def test_webapp_initialization(self, webapp):
        """Test that the webapp initializes correctly."""
        assert webapp.app is not None
        assert webapp.memory_manager is not None
        assert webapp.templates_dir.exists()
        assert webapp.static_dir.exists()
        assert (webapp.static_dir / "style.css").exists()

    def test_memory_tree_rendering(self, webapp):
        """Test the memory tree rendering."""
        # This is a basic smoke test to ensure the function runs without errors
        with webapp.app.app_context():
            result = webapp.render_memory_tree()
            assert "Memory Browser" in result

    def test_memory_entry_rendering(self, webapp, memory_manager):
        """Test rendering a memory entry."""
        with webapp.app.app_context():
            result = webapp.render_memory_entry("test1")
            assert "Test 1" in result
            assert "This is a test entry" in result

    def test_breadcrumb_creation(self, webapp):
        """Test creating breadcrumbs."""
        breadcrumbs = webapp._create_breadcrumbs("folder/nested")
        assert len(breadcrumbs) == 3
        assert breadcrumbs[0]["name"] == "Home"
        assert breadcrumbs[1]["name"] == "folder"
        assert breadcrumbs[2]["name"] == "nested"

    @patch("webbrowser.open")
    @patch("flask.Flask.run")
    def test_run_memory_webapp(self, mock_run, mock_webbrowser, memory_manager):
        """Test running the memory webapp."""
        run_memory_webapp(memory_manager.base_dir, "localhost", 8080)
        mock_webbrowser.assert_called_once_with("http://localhost:8080")
        mock_run.assert_called_once_with(host="localhost", port=8080)
