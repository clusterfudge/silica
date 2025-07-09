"""Tests for installation verification script."""

import subprocess
import sys
from pathlib import Path


def test_verify_installation_script_exists():
    """Test that the verification script exists and is executable."""
    script_path = Path("scripts/verify_installation.py")
    assert script_path.exists(), "Verification script should exist"
    assert script_path.is_file(), "Verification script should be a file"


def test_verify_installation_runs():
    """Test that the verification script runs without errors."""
    script_path = Path("scripts/verify_installation.py")

    # Run the verification script
    result = subprocess.run(
        [sys.executable, str(script_path)], capture_output=True, text=True, timeout=30
    )

    # Should exit with code 0 (success) since we're in a working environment
    assert result.returncode == 0, f"Verification failed: {result.stderr}"
    assert "All checks passed!" in result.stdout


def test_setup_script_exists():
    """Test that the setup script exists and is executable."""
    script_path = Path("scripts/setup_environment.sh")
    assert script_path.exists(), "Setup script should exist"
    assert script_path.is_file(), "Setup script should be a file"


def test_installation_docs_exist():
    """Test that installation documentation exists."""
    docs_path = Path("docs/INSTALLATION.md")
    assert docs_path.exists(), "Installation documentation should exist"
    assert docs_path.is_file(), "Installation documentation should be a file"

    # Check that it contains key sections
    content = docs_path.read_text()
    assert "## System Requirements" in content
    assert "## Raspberry Pi Installation" in content
    assert "Python 3.11" in content
    assert "pyenv" in content


def test_readme_contains_installation_info():
    """Test that README contains installation information."""
    readme_path = Path("README.md")
    assert readme_path.exists(), "README should exist"

    content = readme_path.read_text()
    assert "## Installation" in content
    assert "Raspberry Pi" in content
    assert "Python 3.11" in content
    assert "pysilica" in content


def test_pyproject_has_correct_python_requirement():
    """Test that pyproject.toml has correct Python version requirement."""
    pyproject_path = Path("pyproject.toml")
    assert pyproject_path.exists(), "pyproject.toml should exist"

    content = pyproject_path.read_text()
    assert 'requires-python = ">=3.11"' in content


def test_python_version_file_exists():
    """Test that .python-version file exists and specifies 3.11."""
    version_file = Path(".python-version")
    assert version_file.exists(), ".python-version file should exist"

    content = version_file.read_text().strip()
    assert content == "3.11", f"Expected '3.11', got '{content}'"
