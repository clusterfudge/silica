#!/usr/bin/env python3
"""Tests for Python compatibility utilities."""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add silica to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from silica.utils.python_compatibility import (
    get_python_version,
    find_suitable_python,
    check_uv_python_support,
    configure_uv_python,
)


class TestPythonCompatibility:
    """Test Python compatibility utilities."""

    def test_get_python_version_valid(self):
        """Test getting version from valid Python executable."""
        # Test with current Python interpreter
        version = get_python_version(sys.executable)
        assert version is not None
        assert len(version) == 3
        assert version[0] >= 3  # Should be Python 3.x
        assert all(isinstance(v, int) for v in version)

    def test_get_python_version_invalid(self):
        """Test getting version from invalid executable."""
        version = get_python_version("/nonexistent/python")
        assert version is None

    @patch("subprocess.run")
    def test_get_python_version_parsing(self, mock_run):
        """Test version string parsing."""
        # Mock successful version output
        mock_run.return_value = MagicMock(returncode=0, stdout="Python 3.11.2\n")

        version = get_python_version("python3.11")
        assert version == (3, 11, 2)

    @patch("subprocess.run")
    def test_get_python_version_failed_process(self, mock_run):
        """Test handling of failed process."""
        mock_run.return_value = MagicMock(returncode=1)

        version = get_python_version("python")
        assert version is None

    @patch("shutil.which")
    @patch("silica.utils.python_compatibility.get_python_version")
    def test_find_suitable_python_found(self, mock_get_version, mock_which):
        """Test finding suitable Python when one exists."""
        # Mock that python3.11 exists and has correct version
        mock_which.side_effect = lambda x: "python3.11" if x == "python3.11" else None
        mock_get_version.return_value = (3, 11, 2)

        result = find_suitable_python()
        assert result == "python3.11"

    @patch("shutil.which")
    @patch("silica.utils.python_compatibility.get_python_version")
    def test_find_suitable_python_not_found(self, mock_get_version, mock_which):
        """Test when no suitable Python is found."""
        mock_which.return_value = None
        mock_get_version.return_value = None

        result = find_suitable_python()
        assert result is None

    @patch("shutil.which")
    @patch("silica.utils.python_compatibility.get_python_version")
    def test_find_suitable_python_version_too_old(self, mock_get_version, mock_which):
        """Test when Python version is too old."""
        mock_which.side_effect = (
            lambda x: "/usr/bin/python3" if x == "python3" else None
        )
        mock_get_version.return_value = (3, 7, 0)  # Too old

        result = find_suitable_python()
        assert result is None

    @patch("subprocess.run")
    def test_check_uv_python_support_valid(self, mock_run):
        """Test checking uv support for valid Python."""
        # Mock version check
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Python 3.11.2\n"),  # Version check
            MagicMock(returncode=0, stdout="OK\n"),  # -I flag test
        ]

        result = check_uv_python_support("python3.11")
        assert result is True

    @patch("subprocess.run")
    def test_check_uv_python_support_old_version(self, mock_run):
        """Test checking uv support for old Python version."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Python 3.7.0\n")

        result = check_uv_python_support("python3.7")
        assert result is False

    @patch("subprocess.run")
    def test_check_uv_python_support_no_i_flag(self, mock_run):
        """Test checking uv support when -I flag is not supported."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Python 3.8.0\n"),  # Version check passes
            MagicMock(returncode=1, stdout=""),  # -I flag test fails
        ]

        result = check_uv_python_support("python3.8")
        assert result is False

    @patch.dict(os.environ, {}, clear=True)
    @patch("silica.utils.python_compatibility.find_suitable_python")
    @patch("silica.utils.python_compatibility.check_uv_python_support")
    def test_configure_uv_python_success(self, mock_check_support, mock_find):
        """Test successful uv Python configuration."""
        mock_find.return_value = "/usr/bin/python3.11"
        mock_check_support.return_value = True

        result = configure_uv_python()
        assert result is True
        assert os.environ.get("UV_PYTHON") == "/usr/bin/python3.11"

    @patch.dict(os.environ, {"UV_PYTHON": "/usr/bin/python3.11"})
    @patch("silica.utils.python_compatibility.check_uv_python_support")
    def test_configure_uv_python_existing_valid(self, mock_check_support):
        """Test when UV_PYTHON is already set and valid."""
        mock_check_support.return_value = True

        result = configure_uv_python()
        assert result is True
        assert os.environ.get("UV_PYTHON") == "/usr/bin/python3.11"

    @patch.dict(os.environ, {"UV_PYTHON": "/usr/bin/python2.7"})
    @patch("silica.utils.python_compatibility.check_uv_python_support")
    @patch("silica.utils.python_compatibility.find_suitable_python")
    def test_configure_uv_python_existing_invalid(self, mock_find, mock_check_support):
        """Test when UV_PYTHON is set but invalid."""
        mock_check_support.side_effect = lambda x: x != "/usr/bin/python2.7"
        mock_find.return_value = "/usr/bin/python3.11"

        result = configure_uv_python()
        assert result is True
        assert os.environ.get("UV_PYTHON") == "/usr/bin/python3.11"

    @patch("silica.utils.python_compatibility.find_suitable_python")
    def test_configure_uv_python_no_suitable_found(self, mock_find):
        """Test when no suitable Python is found."""
        mock_find.return_value = None

        result = configure_uv_python()
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__])
