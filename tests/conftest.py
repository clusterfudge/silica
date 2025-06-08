"""Test configuration for silica workspace environment tests.

This file ensures all tests run safely without affecting the current workspace.
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch


@pytest.fixture(scope="session")
def safe_test_environment():
    """Create a completely isolated test environment."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create fake directory structure
        fake_home = temp_path / "fake_home"
        fake_cwd = temp_path / "fake_cwd"
        fake_home.mkdir()
        fake_cwd.mkdir()
        
        with patch.dict(os.environ, {
            'HOME': str(fake_home),
            'SILICA_TEST_MODE': '1'
        }):
            yield {
                'temp_dir': temp_path,
                'fake_home': fake_home,
                'fake_cwd': fake_cwd
            }


@pytest.fixture
def isolated_workspace(safe_test_environment):
    """Provide an isolated workspace for each test."""
    test_workspace = safe_test_environment['temp_dir'] / "test_workspace"
    test_workspace.mkdir()
    
    # Create basic workspace structure
    (test_workspace / ".silica").mkdir()
    
    with patch('silica.cli.commands.workspace_environment.Path.cwd', return_value=test_workspace):
        yield test_workspace


@pytest.fixture
def mock_piku_environment():
    """Mock piku environment without touching real piku setup."""
    with patch('silica.utils.piku.run_piku_in_silica') as mock_piku:
        mock_piku.return_value.returncode = 0
        mock_piku.return_value.stdout = ""
        yield mock_piku


# Ensure we never accidentally touch the real workspace
def pytest_configure(config):
    """Configure pytest to run safely."""
    # Set test mode environment variable
    os.environ['SILICA_TEST_MODE'] = '1'


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add safety markers."""
    for item in items:
        # Add slow marker to integration tests
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.slow)
        
        # Add safety marker to all tests
        item.add_marker(pytest.mark.safe)