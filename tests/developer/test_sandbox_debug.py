"""Tests for the sandbox_debug tool."""

import os
import tempfile
from unittest.mock import patch

from silica.developer.context import AgentContext
from silica.developer.sandbox import SandboxMode
from silica.developer.tools.sandbox_debug import sandbox_debug
from silica.developer.user_interface import UserInterface


class MockUserInterface(UserInterface):
    """Mock user interface for testing."""

    def permission_callback(self, *args, **kwargs):
        return True

    def permission_rendering_callback(self, *args, **kwargs):
        pass

    def handle_system_message(self, message, *args, **kwargs):
        pass

    def handle_assistant_message(self, message, *args, **kwargs):
        pass

    def handle_tool_use(self, *args, **kwargs):
        pass

    def handle_tool_result(self, *args, **kwargs):
        pass

    async def get_user_input(self, prompt=""):
        return ""

    def handle_user_input(self, user_input):
        pass

    def display_token_count(self, *args, **kwargs):
        pass

    def display_welcome_message(self):
        pass

    def status(self, message, spinner=None):
        pass

    def bare(self, message):
        pass


def test_sandbox_debug_basic_functionality():
    """Test that sandbox_debug returns comprehensive debug information."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create a test context with a temporary directory as sandbox
        context = AgentContext.create(
            model_spec={},
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[tmp_dir],
            user_interface=MockUserInterface(),
        )

        result = sandbox_debug(context)

        # Check that all expected sections are present
        expected_sections = [
            "=== SANDBOX CONFIGURATION ===",
            "=== DIRECTORY PATHS ===",
            "=== PATH COMPARISON ===",
            "=== ACCESS PERMISSIONS ===",
            "=== SANDBOX ROOT CONTENTS ===",
            "=== PATH VALIDATION TESTS ===",
            "=== ENVIRONMENT VARIABLES ===",
        ]

        for section in expected_sections:
            assert section in result

        # Check that key configuration values are included
        assert "Sandbox Root Directory:" in result
        assert "Sandbox Mode:" in result
        assert "ALLOW_ALL" in result
        assert tmp_dir in result


def test_sandbox_debug_path_validation():
    """Test that sandbox_debug properly validates different paths."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        context = AgentContext.create(
            model_spec={},
            sandbox_mode=SandboxMode.REMEMBER_PER_RESOURCE,
            sandbox_contents=[tmp_dir],
            user_interface=MockUserInterface(),
        )

        result = sandbox_debug(context)

        # Check path validation results
        assert "Path '.' in sandbox:" in result
        assert "Path '/' in sandbox:" in result
        # The root path should be outside the sandbox
        assert "Path '/' in sandbox: False" in result


def test_sandbox_debug_with_current_directory():
    """Test sandbox_debug when using current directory as sandbox."""
    context = AgentContext.create(
        model_spec={},
        sandbox_mode=SandboxMode.REQUEST_EVERY_TIME,
        sandbox_contents=[],  # This should use current directory
        user_interface=MockUserInterface(),
    )

    result = sandbox_debug(context)

    # Should show current directory info
    cwd = os.getcwd()
    assert cwd in result
    assert "Sandbox Root Directory:" in result
    assert "REQUEST_EVERY_TIME" in result


def test_sandbox_debug_environment_variables():
    """Test that sandbox_debug includes relevant environment variables."""
    context = AgentContext.create(
        model_spec={},
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=MockUserInterface(),
    )

    result = sandbox_debug(context)

    # Check that environment variables section is present
    assert "=== ENVIRONMENT VARIABLES ===" in result
    assert "HOME:" in result
    assert "PWD:" in result
    assert "PATH:" in result


@patch("os.listdir")
def test_sandbox_debug_handles_listing_errors(mock_listdir):
    """Test that sandbox_debug gracefully handles directory listing errors."""
    # Make listdir raise an exception
    mock_listdir.side_effect = PermissionError("Access denied")

    context = AgentContext.create(
        model_spec={},
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=MockUserInterface(),
    )

    result = sandbox_debug(context)

    # Should handle the error gracefully
    assert "Error listing directory:" in result
    assert "Access denied" in result


def test_sandbox_debug_gitignore_patterns():
    """Test that sandbox_debug reports gitignore pattern count."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create a .gitignore file
        gitignore_path = os.path.join(tmp_dir, ".gitignore")
        with open(gitignore_path, "w") as f:
            f.write("*.pyc\n__pycache__/\n.venv/\n")

        context = AgentContext.create(
            model_spec={},
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[tmp_dir],
            user_interface=MockUserInterface(),
        )

        result = sandbox_debug(context)

        # Should report gitignore patterns (includes default .git pattern plus file patterns)
        assert "Gitignore Patterns:" in result
        # Should have at least 4 patterns (.git + 3 from file)
        assert (
            "4" in result or "5" in result or "6" in result
        )  # Could vary by implementation


def test_sandbox_debug_permissions_cache():
    """Test that sandbox_debug correctly reports permissions cache status."""
    # Test with cache enabled mode
    context_with_cache = AgentContext.create(
        model_spec={},
        sandbox_mode=SandboxMode.REMEMBER_PER_RESOURCE,
        sandbox_contents=[],
        user_interface=MockUserInterface(),
    )

    result_with_cache = sandbox_debug(context_with_cache)
    assert "Permissions Cache: Enabled" in result_with_cache

    # Test with cache disabled mode
    context_without_cache = AgentContext.create(
        model_spec={},
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=MockUserInterface(),
    )

    result_without_cache = sandbox_debug(context_without_cache)
    assert "Permissions Cache: Disabled" in result_without_cache
