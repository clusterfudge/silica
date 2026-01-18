"""
Tests for ripgrep integration in memory tools.
"""

import shutil
from unittest.mock import patch

from silica.developer.tools.memory import _has_ripgrep, _refresh_ripgrep_cache


def test_has_ripgrep_detection():
    """Test that ripgrep detection works correctly."""
    # Reset cache before testing
    _refresh_ripgrep_cache()

    # Test when ripgrep is available
    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/rg"
        assert _has_ripgrep() is True
        mock_which.assert_called_once_with("rg")

    # Reset cache and test when ripgrep is not available
    _refresh_ripgrep_cache()
    with patch("shutil.which") as mock_which:
        mock_which.return_value = None
        assert _has_ripgrep() is False
        mock_which.assert_called_once_with("rg")

    # Reset cache for other tests
    _refresh_ripgrep_cache()


def test_has_ripgrep_real():
    """Test actual ripgrep detection on the system."""
    # Reset cache to ensure fresh check
    _refresh_ripgrep_cache()

    # This will return True if ripgrep is installed, False otherwise
    result = _has_ripgrep()
    assert isinstance(result, bool)

    # Verify it matches shutil.which behavior
    assert result == (shutil.which("rg") is not None)


def test_ripgrep_caching_efficiency():
    """Test that ripgrep detection is cached for efficiency."""
    # Reset cache to ensure clean test
    _refresh_ripgrep_cache()

    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/rg"

        # First call should hit shutil.which
        result1 = _has_ripgrep()
        assert result1 is True
        assert mock_which.call_count == 1

        # Subsequent calls should use cache, not call shutil.which again
        result2 = _has_ripgrep()
        result3 = _has_ripgrep()
        assert result2 is True
        assert result3 is True
        assert mock_which.call_count == 1  # Still only called once

    # Reset cache for other tests
    _refresh_ripgrep_cache()


def test_refresh_ripgrep_cache():
    """Test that cache refresh works correctly."""
    _refresh_ripgrep_cache()

    with patch("shutil.which") as mock_which:
        # First call - ripgrep available
        mock_which.return_value = "/usr/bin/rg"
        result1 = _has_ripgrep()
        assert result1 is True
        assert mock_which.call_count == 1

        # Change mock return value and refresh cache
        mock_which.return_value = None
        _refresh_ripgrep_cache()

        # Next call should re-check and get new result
        result2 = _has_ripgrep()
        assert result2 is False
        assert mock_which.call_count == 2  # Called again after refresh

    # Reset cache for other tests
    _refresh_ripgrep_cache()


def test_system_message_includes_ripgrep():
    """Test that system messages dynamically include ripgrep guidance when available."""
    from silica.developer.prompt import create_system_message
    from unittest.mock import Mock

    # Mock agent context
    mock_context = Mock()
    mock_context.sandbox.get_directory_listing.return_value = []
    mock_context.memory_manager.get_tree.return_value = {"items": []}

    with patch("silica.developer.tools.memory._has_ripgrep", return_value=True):
        sections = create_system_message(
            mock_context, include_sandbox=False, include_memory=False
        )
        # Should have default section + ripgrep section + loop prevention section
        assert len(sections) == 3
        # Find ripgrep section
        ripgrep_sections = [s for s in sections if "ripgrep" in s["text"].lower()]
        assert len(ripgrep_sections) == 1
        assert "File Search Best Practices" in ripgrep_sections[0]["text"]

    with patch("silica.developer.tools.memory._has_ripgrep", return_value=False):
        sections = create_system_message(
            mock_context, include_sandbox=False, include_memory=False
        )
        # Should have default section + loop prevention section (no ripgrep)
        assert len(sections) == 2
        # Verify no ripgrep section
        ripgrep_sections = [s for s in sections if "ripgrep" in s["text"].lower()]
        assert len(ripgrep_sections) == 0


def test_system_message_with_custom_section():
    """Test that ripgrep guidance is added even with custom system sections."""
    from silica.developer.prompt import create_system_message
    from unittest.mock import Mock

    mock_context = Mock()
    mock_context.sandbox.get_directory_listing.return_value = []
    mock_context.memory_manager.get_tree.return_value = {"items": []}

    custom_section = {"type": "text", "text": "Custom system prompt"}

    with patch("silica.developer.tools.memory._has_ripgrep", return_value=True):
        sections = create_system_message(
            mock_context,
            system_section=custom_section,
            include_sandbox=False,
            include_memory=False,
        )
        # Should have custom section (wrapped in persona tags) + ripgrep section + loop prevention section
        assert len(sections) == 3
        assert "Custom system prompt" in sections[0]["text"]
        assert "<persona" in sections[0]["text"]  # Should be wrapped in persona tags
        assert "</persona>" in sections[0]["text"]
        # Find ripgrep section
        ripgrep_sections = [s for s in sections if "ripgrep" in s["text"].lower()]
        assert len(ripgrep_sections) == 1
