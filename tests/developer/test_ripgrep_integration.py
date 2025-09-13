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


def test_system_prompt_includes_ripgrep():
    """Test that system prompts dynamically include ripgrep guidance when available."""
    from silica.developer.prompt import _get_system_section_text

    with patch("silica.developer.tools.memory._has_ripgrep", return_value=True):
        system_text_with_rg = _get_system_section_text()
        assert "ripgrep" in system_text_with_rg.lower()
        assert "File Search Best Practices" in system_text_with_rg
        assert 'rg "pattern"' in system_text_with_rg
        assert "faster" in system_text_with_rg

    with patch("silica.developer.tools.memory._has_ripgrep", return_value=False):
        system_text_without_rg = _get_system_section_text()
        assert "ripgrep" not in system_text_without_rg.lower()
        assert "File Search Best Practices" not in system_text_without_rg
        assert "rg " not in system_text_without_rg


def test_system_prompt_dynamic_loading():
    """Test that the system prompt is generated dynamically each time."""
    from silica.developer.prompt import _get_default_system_section

    # Two calls should generate fresh content each time
    with patch("silica.developer.tools.memory._has_ripgrep", return_value=True):
        section1 = _get_default_system_section()
        assert "ripgrep" in section1["text"].lower()

    with patch("silica.developer.tools.memory._has_ripgrep", return_value=False):
        section2 = _get_default_system_section()
        assert "ripgrep" not in section2["text"].lower()
