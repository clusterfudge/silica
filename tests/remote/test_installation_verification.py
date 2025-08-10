"""Tests for Raspberry Pi deployment installation scripts."""

from pathlib import Path


def test_remote_setup_script_exists():
    """Test that the remote setup script exists in templates."""
    script_path = Path("silica/remote/utils/templates/setup_python.sh")
    assert script_path.exists(), "Remote setup script should exist"
    assert script_path.is_file(), "Remote setup script should be a file"


def test_remote_verify_script_exists():
    """Test that the remote verification script exists in templates."""
    script_path = Path("silica/remote/utils/templates/verify_setup.py")
    assert script_path.exists(), "Remote verification script should exist"
    assert script_path.is_file(), "Remote verification script should be a file"


def test_installation_docs_exist():
    """Test that installation documentation exists."""
    docs_path = Path("docs/remote/INSTALLATION.md")
    assert docs_path.exists(), "Installation documentation should exist"
    assert docs_path.is_file(), "Installation documentation should be a file"

    # Check that it contains key sections
    content = docs_path.read_text()
    assert "## Local Development Installation" in content
    assert "## Remote Deployment (Raspberry Pi)" in content
    assert "Python 3.11" in content


def test_raspberry_pi_deployment_docs_exist():
    """Test that Raspberry Pi deployment documentation exists."""
    docs_path = Path("docs/remote/RASPBERRY_PI_DEPLOYMENT.md")
    assert docs_path.exists(), "Raspberry Pi deployment documentation should exist"
    assert docs_path.is_file(), "Raspberry Pi deployment documentation should be a file"

    # Check that it contains key sections
    content = docs_path.read_text()
    assert "## Deployment Process" in content
    assert "### 2. Automatic Python Setup" in content
    assert "pyenv" in content


def test_readme_contains_installation_info():
    """Test that README contains installation information."""
    readme_path = Path("README.md")
    assert readme_path.exists(), "README should exist"

    content = readme_path.read_text()
    assert "## Installation" in content
    assert "Raspberry Pi Deployment" in content
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


def test_template_files_exist():
    """Test that all required template files exist."""
    template_files = [
        "setup_python.sh",
        "verify_setup.py",
        "pyproject.toml",
        "requirements.txt",
        "Procfile",
        ".python-version",
        ".gitignore",
    ]

    for filename in template_files:
        template_path = Path(f"silica/remote/utils/templates/{filename}")
        assert template_path.exists(), f"Template file {filename} should exist"
        assert template_path.is_file(), f"Template file {filename} should be a file"
