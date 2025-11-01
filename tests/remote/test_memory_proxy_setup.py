"""Tests for memory-proxy CLI commands."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_home(tmp_path):
    """Mock home directory for testing."""
    return tmp_path


@pytest.fixture
def mock_silica_dirs(mock_home, monkeypatch):
    """Set up mock silica directories."""
    silica_dir = mock_home / ".silica"
    memory_proxy_dir = silica_dir / "memory-proxy"
    config_file = silica_dir / "config.env"

    # Patch the module-level constants
    monkeypatch.setattr(
        "silica.remote.cli.commands.memory_proxy.SILICA_DIR", silica_dir
    )
    monkeypatch.setattr(
        "silica.remote.cli.commands.memory_proxy.MEMORY_PROXY_DIR", memory_proxy_dir
    )
    monkeypatch.setattr(
        "silica.remote.cli.commands.memory_proxy.CONFIG_FILE", config_file
    )

    return {
        "silica_dir": silica_dir,
        "memory_proxy_dir": memory_proxy_dir,
        "config_file": config_file,
    }


def test_memory_proxy_dir_is_separate_from_silica_dir(mock_silica_dirs):
    """Test that memory-proxy files are isolated in their own directory."""
    from silica.remote.cli.commands.memory_proxy import (
        MEMORY_PROXY_DIR,
        SILICA_DIR,
    )

    # Verify the directories are different
    assert MEMORY_PROXY_DIR != SILICA_DIR
    assert MEMORY_PROXY_DIR.parent == SILICA_DIR
    assert MEMORY_PROXY_DIR.name == "memory-proxy"


def test_ensure_memory_proxy_dir_creates_directory(mock_silica_dirs):
    """Test that _ensure_memory_proxy_dir creates the directory."""
    from silica.remote.cli.commands.memory_proxy import _ensure_memory_proxy_dir

    memory_proxy_dir = mock_silica_dirs["memory_proxy_dir"]

    # Directory should not exist initially
    assert not memory_proxy_dir.exists()

    # Call the function
    result = _ensure_memory_proxy_dir()

    # Directory should now exist
    assert memory_proxy_dir.exists()
    assert result == memory_proxy_dir


def test_create_procfile_writes_to_memory_proxy_dir(mock_silica_dirs):
    """Test that Procfile is created in memory-proxy directory."""
    from silica.remote.cli.commands.memory_proxy import (
        _create_procfile,
        _ensure_memory_proxy_dir,
    )

    memory_proxy_dir = mock_silica_dirs["memory_proxy_dir"]
    _ensure_memory_proxy_dir()

    # Create Procfile
    _create_procfile()

    # Verify it exists in the right place
    procfile = memory_proxy_dir / "Procfile"
    assert procfile.exists()
    assert "uvicorn silica.memory_proxy.app:app" in procfile.read_text()


def test_check_dokku_app_exists_returns_true_when_app_exists(mock_silica_dirs):
    """Test that _check_dokku_app_exists detects existing apps."""
    from silica.remote.cli.commands.memory_proxy import _check_dokku_app_exists

    with patch("subprocess.run") as mock_run:
        # Mock successful response with app name in output
        mock_run.return_value = MagicMock(
            returncode=0, stdout="=====> My Apps\nmemory-proxy\nother-app\n"
        )

        result = _check_dokku_app_exists("dokku@server", "memory-proxy")
        assert result is True


def test_check_dokku_app_exists_returns_false_when_app_missing(mock_silica_dirs):
    """Test that _check_dokku_app_exists returns False for missing apps."""
    from silica.remote.cli.commands.memory_proxy import _check_dokku_app_exists

    with patch("subprocess.run") as mock_run:
        # Mock successful response without app name
        mock_run.return_value = MagicMock(
            returncode=0, stdout="=====> My Apps\nother-app\n"
        )

        result = _check_dokku_app_exists("dokku@server", "memory-proxy")
        assert result is False


def test_create_dokku_app_creates_app_when_missing(mock_silica_dirs):
    """Test that _create_dokku_app creates a new app."""
    from silica.remote.cli.commands.memory_proxy import _create_dokku_app

    with patch("subprocess.run") as mock_run:
        # First call: app doesn't exist
        # Second call: create app succeeds
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="=====> My Apps\nother-app\n"),
            MagicMock(returncode=0, stdout="App created\n", stderr=""),
        ]

        # Should not raise
        _create_dokku_app("dokku@server", "memory-proxy")

        # Verify ssh command was called
        calls = mock_run.call_args_list
        assert len(calls) == 2
        assert "apps:create" in str(calls[1])


def test_create_dokku_app_skips_when_exists(mock_silica_dirs):
    """Test that _create_dokku_app skips creation if app exists."""
    from silica.remote.cli.commands.memory_proxy import _create_dokku_app

    with patch("subprocess.run") as mock_run:
        # App already exists
        mock_run.return_value = MagicMock(
            returncode=0, stdout="=====> My Apps\nmemory-proxy\n"
        )

        # Should not raise and should only check, not create
        _create_dokku_app("dokku@server", "memory-proxy")

        # Only one call (the check)
        assert mock_run.call_count == 1


def test_create_dokku_app_raises_on_failure(mock_silica_dirs):
    """Test that _create_dokku_app raises on creation failure."""
    from silica.remote.cli.commands.memory_proxy import _create_dokku_app

    with patch("subprocess.run") as mock_run:
        # First call: app doesn't exist
        # Second call: create app fails
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="=====> My Apps\nother-app\n"),
            MagicMock(returncode=1, stdout="", stderr="Error creating app"),
        ]

        # Should raise
        with pytest.raises(RuntimeError, match="Failed to create dokku app"):
            _create_dokku_app("dokku@server", "memory-proxy")


def test_git_operations_use_memory_proxy_dir(mock_silica_dirs):
    """Test that git operations happen in the memory-proxy directory."""
    from silica.remote.cli.commands.memory_proxy import (
        _ensure_memory_proxy_dir,
        _init_git_repo,
    )

    memory_proxy_dir = mock_silica_dirs["memory_proxy_dir"]
    _ensure_memory_proxy_dir()

    # Create some files
    (memory_proxy_dir / "Procfile").write_text("web: echo test\n")
    (memory_proxy_dir / "requirements.txt").write_text("silica\n")

    # Initialize git
    _init_git_repo()

    # Verify git repo is in the right place
    assert (memory_proxy_dir / ".git").exists()
    assert not (mock_silica_dirs["silica_dir"] / ".git").exists()


def test_config_file_remains_in_silica_dir(mock_silica_dirs):
    """Test that config.env is stored in ~/.silica, not memory-proxy dir."""
    from silica.remote.cli.commands.memory_proxy import (
        CONFIG_FILE,
        MEMORY_PROXY_DIR,
        SILICA_DIR,
    )

    # Config should be in SILICA_DIR, not MEMORY_PROXY_DIR
    assert CONFIG_FILE.parent == SILICA_DIR
    assert CONFIG_FILE.parent != MEMORY_PROXY_DIR


def test_requirements_txt_uses_pysilica_package_name(mock_silica_dirs):
    """Test that requirements.txt uses 'pysilica' not 'silica'."""
    from silica.remote.cli.commands.memory_proxy import (
        _create_requirements,
        _ensure_memory_proxy_dir,
    )

    memory_proxy_dir = mock_silica_dirs["memory_proxy_dir"]
    _ensure_memory_proxy_dir()

    # Test with specific version
    _create_requirements("0.8.0")
    req_file = memory_proxy_dir / "requirements.txt"
    assert req_file.exists()
    content = req_file.read_text()
    assert "pysilica==0.8.0" in content
    # Ensure it's not just "silica==" (without the "py" prefix)
    assert not content.strip().startswith("silica==")

    # Test without version (uses current or latest)
    _create_requirements()
    content = req_file.read_text()
    assert "pysilica" in content
    assert content.strip().startswith("pysilica")
