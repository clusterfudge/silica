"""
Tests for ripgrep integration in memory tools.
"""

import shutil
from unittest.mock import patch

from silica.developer.tools.memory import _has_ripgrep


def test_has_ripgrep_detection():
    """Test that ripgrep detection works correctly."""
    # Test when ripgrep is available
    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/rg"
        assert _has_ripgrep() is True
        mock_which.assert_called_once_with("rg")

    # Test when ripgrep is not available
    with patch("shutil.which") as mock_which:
        mock_which.return_value = None
        assert _has_ripgrep() is False
        mock_which.assert_called_once_with("rg")


def test_has_ripgrep_real():
    """Test actual ripgrep detection on the system."""
    # This will return True if ripgrep is installed, False otherwise
    result = _has_ripgrep()
    assert isinstance(result, bool)

    # Verify it matches shutil.which behavior
    assert result == (shutil.which("rg") is not None)
