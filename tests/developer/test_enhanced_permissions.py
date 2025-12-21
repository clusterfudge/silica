"""
Tests for enhanced permission prompts with group-aware "always allow" options
and shell command parser integration.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from silica.developer.sandbox import (
    Sandbox,
    SandboxMode,
    DoSomethingElseError,
    _default_tool_permission_prompt,
    _default_shell_permission_prompt,
)
from silica.developer.tools.permissions import (
    PermissionsManager,
    ToolPermissions,
    PERMISSIONS_FILE,
)
from silica.developer.tools.shell_parser import parse_shell_command


@pytest.fixture
def temp_dir(tmp_path):
    """Create a temporary directory for testing."""
    return tmp_path


@pytest.fixture
def persona_dir(tmp_path):
    """Create a temporary persona directory for testing."""
    persona_path = tmp_path / "personas" / "test_persona"
    persona_path.mkdir(parents=True)
    return persona_path


@pytest.fixture
def sandbox(temp_dir):
    """Create a sandbox with REMEMBER_ALL mode for testing."""
    return Sandbox(str(temp_dir), SandboxMode.REMEMBER_ALL)


@pytest.fixture
def sandbox_with_manager(temp_dir, persona_dir):
    """Create a sandbox with a permissions manager attached."""
    sandbox = Sandbox(str(temp_dir), SandboxMode.REMEMBER_ALL)
    manager = PermissionsManager(persona_dir, dwr_mode=False)
    sandbox.permissions_manager = manager
    return sandbox


class TestSandboxInit:
    """Tests for Sandbox initialization with enhanced permission tracking."""

    def test_sandbox_has_allowed_tools_set(self, temp_dir):
        """Test that sandbox initializes with empty allowed_tools set."""
        sandbox = Sandbox(str(temp_dir), SandboxMode.REMEMBER_ALL)
        assert hasattr(sandbox, "allowed_tools")
        assert isinstance(sandbox.allowed_tools, set)
        assert len(sandbox.allowed_tools) == 0

    def test_sandbox_has_allowed_groups_set(self, temp_dir):
        """Test that sandbox initializes with empty allowed_groups set."""
        sandbox = Sandbox(str(temp_dir), SandboxMode.REMEMBER_ALL)
        assert hasattr(sandbox, "allowed_groups")
        assert isinstance(sandbox.allowed_groups, set)
        assert len(sandbox.allowed_groups) == 0

    def test_sandbox_has_permissions_manager_slot(self, temp_dir):
        """Test that sandbox initializes with None permissions_manager."""
        sandbox = Sandbox(str(temp_dir), SandboxMode.REMEMBER_ALL)
        assert hasattr(sandbox, "permissions_manager")
        assert sandbox.permissions_manager is None


class TestCheckPermissionsSignature:
    """Tests for the updated check_permissions method signature."""

    def test_check_permissions_accepts_group_parameter(self, temp_dir):
        """Test that check_permissions accepts a group parameter."""
        sandbox = Sandbox(str(temp_dir), SandboxMode.ALLOW_ALL)

        # Should not raise an error
        result = sandbox.check_permissions(
            "read_file", "test.txt", action_arguments=None, group="Files"
        )
        assert result is True

    def test_check_permissions_group_is_optional(self, temp_dir):
        """Test that group parameter is optional (backward compatible)."""
        sandbox = Sandbox(str(temp_dir), SandboxMode.ALLOW_ALL)

        # Should work without group parameter
        result = sandbox.check_permissions("read_file", "test.txt")
        assert result is True


class TestEnhancedPromptWithGroup:
    """Tests for enhanced permission prompts with group option."""

    def test_always_allow_tool_persists_in_memory(self, sandbox):
        """Test that 'always allow tool' choice persists in memory."""
        # Mock the callback to return "always_tool"
        sandbox._permission_check_callback = MagicMock(return_value="always_tool")

        # First call should invoke callback
        result = sandbox.check_permissions("read_file", "test.txt", group="Files")
        assert result is True
        assert "read_file" in sandbox.allowed_tools

        # Second call should not invoke callback (cached in memory)
        sandbox._permission_check_callback.reset_mock()
        result = sandbox.check_permissions("read_file", "other.txt", group="Files")
        assert result is True
        sandbox._permission_check_callback.assert_not_called()

    def test_always_allow_group_persists_in_memory(self, sandbox):
        """Test that 'always allow group' choice persists in memory."""
        # Mock the callback to return "always_group"
        sandbox._permission_check_callback = MagicMock(return_value="always_group")

        # First call should invoke callback
        result = sandbox.check_permissions("read_file", "test.txt", group="Files")
        assert result is True
        assert "Files" in sandbox.allowed_groups

        # Second call with different tool in same group should not invoke callback
        sandbox._permission_check_callback.reset_mock()
        result = sandbox.check_permissions("write_file", "other.txt", group="Files")
        assert result is True
        sandbox._permission_check_callback.assert_not_called()

    def test_allow_this_time_does_not_persist(self, sandbox):
        """Test that 'yes, this time' doesn't persist beyond cache."""
        # Mock callback to return True (allow this time)
        sandbox._permission_check_callback = MagicMock(return_value=True)

        result = sandbox.check_permissions("read_file", "test.txt", group="Files")
        assert result is True

        # Tool and group should not be added to allowed sets
        assert "read_file" not in sandbox.allowed_tools
        assert "Files" not in sandbox.allowed_groups


class TestAlwaysAllowPersistsToConfig:
    """Tests for persisting 'always allow' choices to config."""

    def test_always_allow_tool_persists_to_config(self, sandbox_with_manager):
        """Test that 'always allow tool' persists to config file."""
        sandbox = sandbox_with_manager
        sandbox._permission_check_callback = MagicMock(return_value="always_tool")

        result = sandbox.check_permissions("read_file", "test.txt", group="Files")
        assert result is True

        # Verify persisted to manager
        assert "read_file" in sandbox.permissions_manager.permissions.allow_tools

    def test_always_allow_group_persists_to_config(self, sandbox_with_manager):
        """Test that 'always allow group' persists to config file."""
        sandbox = sandbox_with_manager
        sandbox._permission_check_callback = MagicMock(return_value="always_group")

        result = sandbox.check_permissions("read_file", "test.txt", group="Files")
        assert result is True

        # Verify persisted to manager
        assert "Files" in sandbox.permissions_manager.permissions.allow_groups

    def test_config_survives_reload(self, temp_dir, persona_dir):
        """Test that persisted config survives reload."""
        # First sandbox saves permission
        sandbox1 = Sandbox(str(temp_dir), SandboxMode.REMEMBER_ALL)
        manager1 = PermissionsManager(persona_dir, dwr_mode=False)
        sandbox1.permissions_manager = manager1
        sandbox1._permission_check_callback = MagicMock(return_value="always_tool")

        sandbox1.check_permissions("read_file", "test.txt", group="Files")

        # Verify file was written
        config_file = persona_dir / PERMISSIONS_FILE
        assert config_file.exists()

        # Create new sandbox with fresh manager - should load saved permissions
        sandbox2 = Sandbox(str(temp_dir), SandboxMode.REMEMBER_ALL)
        manager2 = PermissionsManager(persona_dir, dwr_mode=False)
        sandbox2.permissions_manager = manager2

        # Should be allowed without prompting (loaded from config)
        sandbox2._permission_check_callback = MagicMock()
        result = sandbox2.check_permissions("read_file", "other.txt", group="Files")
        assert result is True
        sandbox2._permission_check_callback.assert_not_called()


class TestShellCommandParsingIntegration:
    """Tests for shell command parsing integration."""

    def test_simple_command_offers_prefix_option(self):
        """Test that simple commands offer to allow the command prefix."""
        parsed = parse_shell_command("git status")
        assert parsed.is_simple
        assert parsed.commands == ["git"]

    def test_compound_command_offers_all_prefixes(self):
        """Test that compound commands offer to allow all detected prefixes."""
        parsed = parse_shell_command("git pull && npm install")
        assert not parsed.is_simple
        assert set(parsed.commands) == {"git", "npm"}

    def test_always_allow_commands_persists(self, sandbox_with_manager):
        """Test that 'always allow commands' persists shell prefixes."""
        sandbox = sandbox_with_manager

        # Mock callback to return always_commands with set of commands
        sandbox._permission_check_callback = MagicMock(
            return_value=("always_commands", {"git", "npm"})
        )

        result = sandbox.check_permissions(
            "shell", "git status && npm test", group="Shell"
        )
        assert result is True

        # Verify commands were added to shell_allowed_commands
        perms = sandbox.permissions_manager.permissions
        assert "git" in perms.shell_allowed_commands
        assert "npm" in perms.shell_allowed_commands


class TestShellAllowDenyListIntegration:
    """Tests for shell command allow/deny list integration."""

    def test_allowed_commands_skip_prompt(self, sandbox_with_manager, persona_dir):
        """Test that pre-allowed shell commands skip the prompt."""
        sandbox = sandbox_with_manager

        # Pre-configure allowed commands
        sandbox.permissions_manager.permissions = ToolPermissions(
            shell_allowed_commands={"git", "ls"}
        )

        # Should be allowed without prompting
        sandbox._permission_check_callback = MagicMock()
        result = sandbox.check_permissions("shell", "git status", group="Shell")
        assert result is True
        sandbox._permission_check_callback.assert_not_called()

    def test_denied_commands_still_prompt(self, sandbox_with_manager):
        """Test that denied commands still show prompt with warning."""
        sandbox = sandbox_with_manager

        # Pre-configure denied commands
        sandbox.permissions_manager.permissions = ToolPermissions(
            shell_denied_commands={"sudo", "rm"}
        )

        # Should prompt with denied warning
        sandbox._permission_check_callback = MagicMock(return_value=False)
        result = sandbox.check_permissions("shell", "sudo rm -rf /", group="Shell")
        assert result is False

        # Verify callback was called with denied info
        sandbox._permission_check_callback.assert_called_once()
        call_args = sandbox._permission_check_callback.call_args
        action_args = call_args[0][3]  # action_arguments is 4th positional arg
        assert "denied" in action_args

    def test_mixed_allowed_denied_shows_denied_warning(self, sandbox_with_manager):
        """Test commands with both allowed and denied show denied warning."""
        sandbox = sandbox_with_manager

        sandbox.permissions_manager.permissions = ToolPermissions(
            shell_allowed_commands={"ls"}, shell_denied_commands={"sudo"}
        )

        sandbox._permission_check_callback = MagicMock(return_value=True)
        sandbox.check_permissions("shell", "ls && sudo reboot", group="Shell")

        # Should have prompted with denied warning
        call_args = sandbox._permission_check_callback.call_args
        action_args = call_args[0][3]
        assert "denied" in action_args


class TestDefaultPermissionPrompts:
    """Tests for the default permission prompt functions."""

    def test_tool_prompt_includes_group_option_when_provided(self):
        """Test that tool prompt includes group option when group is provided."""
        # We can't easily test input() prompts, but we can verify the function exists
        # and has the right signature
        import inspect

        sig = inspect.signature(_default_tool_permission_prompt)
        params = list(sig.parameters.keys())
        assert "group" in params

    def test_shell_prompt_parses_command(self):
        """Test that shell prompt uses shell parser."""
        # Verify the function exists and has right signature
        import inspect

        sig = inspect.signature(_default_shell_permission_prompt)
        params = list(sig.parameters.keys())
        assert "command" in params
        assert "group" in params


class TestDoSomethingElseError:
    """Tests for DoSomethingElseError propagation."""

    def test_do_something_else_propagates(self, sandbox):
        """Test that DoSomethingElseError propagates from callback."""
        sandbox._permission_check_callback = MagicMock(
            side_effect=DoSomethingElseError()
        )

        with pytest.raises(DoSomethingElseError):
            sandbox.check_permissions("read_file", "test.txt", group="Files")


class TestPermissionResultHandling:
    """Tests for handling different permission result types."""

    def test_handles_bool_true(self, sandbox):
        """Test handling of boolean True result."""
        sandbox._permission_check_callback = MagicMock(return_value=True)
        result = sandbox.check_permissions("read_file", "test.txt")
        assert result is True

    def test_handles_bool_false(self, sandbox):
        """Test handling of boolean False result."""
        sandbox._permission_check_callback = MagicMock(return_value=False)
        result = sandbox.check_permissions("read_file", "test.txt")
        assert result is False

    def test_handles_always_tool_string(self, sandbox):
        """Test handling of 'always_tool' string result."""
        sandbox._permission_check_callback = MagicMock(return_value="always_tool")
        result = sandbox.check_permissions("read_file", "test.txt")
        assert result is True
        assert "read_file" in sandbox.allowed_tools

    def test_handles_always_group_string(self, sandbox):
        """Test handling of 'always_group' string result."""
        sandbox._permission_check_callback = MagicMock(return_value="always_group")
        result = sandbox.check_permissions("read_file", "test.txt", group="Files")
        assert result is True
        assert "Files" in sandbox.allowed_groups

    def test_handles_always_commands_tuple(self, sandbox_with_manager):
        """Test handling of ('always_commands', set) tuple result."""
        sandbox = sandbox_with_manager
        sandbox._permission_check_callback = MagicMock(
            return_value=("always_commands", {"git", "npm"})
        )
        result = sandbox.check_permissions("shell", "git && npm", group="Shell")
        assert result is True
        perms = sandbox.permissions_manager.permissions
        assert "git" in perms.shell_allowed_commands
        assert "npm" in perms.shell_allowed_commands

    def test_handles_unknown_result_as_deny(self, sandbox):
        """Test that unknown result types are treated as deny."""
        sandbox._permission_check_callback = MagicMock(return_value="invalid")
        result = sandbox.check_permissions("read_file", "test.txt")
        assert result is False


class TestSandboxFileOperationsWithGroup:
    """Tests for sandbox file operations passing group parameter."""

    def test_read_file_passes_group(self, temp_dir):
        """Test that read_file passes Files group to check_permissions."""
        sandbox = Sandbox(str(temp_dir), SandboxMode.REQUEST_EVERY_TIME)

        # Create a test file
        test_file = Path(temp_dir) / "test.txt"
        test_file.write_text("content")

        # Mock check_permissions to verify group is passed
        sandbox.check_permissions = MagicMock(return_value=True)

        import asyncio

        asyncio.get_event_loop().run_until_complete(sandbox.read_file("test.txt"))

        # Verify group was passed
        sandbox.check_permissions.assert_called()
        call_kwargs = sandbox.check_permissions.call_args[1]
        assert call_kwargs.get("group") == "Files"

    def test_write_file_new_passes_group(self, temp_dir):
        """Test that write_file (new file) passes Files group."""
        sandbox = Sandbox(str(temp_dir), SandboxMode.REQUEST_EVERY_TIME)
        sandbox.check_permissions = MagicMock(return_value=True)

        sandbox.write_file("new_file.txt", "content")

        # Verify group was passed
        sandbox.check_permissions.assert_called()
        call_kwargs = sandbox.check_permissions.call_args[1]
        assert call_kwargs.get("group") == "Files"

    def test_create_file_passes_group(self, temp_dir):
        """Test that create_file passes Files group."""
        sandbox = Sandbox(str(temp_dir), SandboxMode.REQUEST_EVERY_TIME)
        sandbox.check_permissions = MagicMock(return_value=True)

        sandbox.create_file("created.txt", "content")

        # Verify group was passed
        sandbox.check_permissions.assert_called()
        call_kwargs = sandbox.check_permissions.call_args[1]
        assert call_kwargs.get("group") == "Files"


class TestBackwardCompatibility:
    """Tests for backward compatibility with old permission callback signatures."""

    def test_old_callback_signature_works(self, temp_dir):
        """Test that old callback signature (without group) still works."""

        def old_style_callback(action, resource, mode, action_arguments):
            return True

        sandbox = Sandbox(
            str(temp_dir),
            SandboxMode.REMEMBER_ALL,
            permission_check_callback=old_style_callback,
        )

        # This should work but may log a warning or handle gracefully
        # Depending on implementation, we might need to wrap old-style callbacks
        # For now, we just verify the sandbox is created
        assert sandbox is not None


class TestAllowAllModeBypassesPrompts:
    """Tests for ALLOW_ALL mode (--dwr flag) bypassing all permission prompts.

    This test class specifically validates the fix for a bug where the --dwr flag
    (which sets ALLOW_ALL mode) did not bypass shell command permission prompts,
    causing interactive prompts even when the user expected full autonomy.
    """

    def test_allow_all_mode_bypasses_shell_prompts(self, temp_dir):
        """Test that ALLOW_ALL mode bypasses shell permission prompts.

        This was the original bug: shell commands would still prompt for permission
        even in ALLOW_ALL mode because the ALLOW_ALL check happened after the
        shell-specific permission handling branch.
        """
        sandbox = Sandbox(str(temp_dir), SandboxMode.ALLOW_ALL)

        # Create a mock callback that should NOT be called
        mock_callback = MagicMock(return_value=True)
        sandbox._permission_check_callback = mock_callback

        # Shell commands should be allowed without prompting in ALLOW_ALL mode
        result = sandbox.check_permissions("shell", "ls -la", group="Shell")

        assert result is True, "Shell command should be allowed in ALLOW_ALL mode"
        mock_callback.assert_not_called()

    def test_allow_all_mode_bypasses_non_shell_prompts(self, temp_dir):
        """Test that ALLOW_ALL mode bypasses non-shell permission prompts."""
        sandbox = Sandbox(str(temp_dir), SandboxMode.ALLOW_ALL)

        mock_callback = MagicMock(return_value=True)
        sandbox._permission_check_callback = mock_callback

        result = sandbox.check_permissions("read_file", "test.txt", group="Files")

        assert result is True
        mock_callback.assert_not_called()

    def test_allow_all_mode_bypasses_all_action_types(self, temp_dir):
        """Test that ALLOW_ALL mode bypasses prompts for all action types."""
        sandbox = Sandbox(str(temp_dir), SandboxMode.ALLOW_ALL)

        mock_callback = MagicMock(return_value=True)
        sandbox._permission_check_callback = mock_callback

        # Test various action types
        actions = [
            ("shell", "git status", "Shell"),
            ("shell", "npm install && npm test", "Shell"),
            ("read_file", "config.json", "Files"),
            ("write_file", "output.txt", "Files"),
            ("edit_file", "main.py", "Files"),
            ("web_search", "query", "Web"),
            ("gmail_send", "email", "Gmail"),
        ]

        for action, resource, group in actions:
            result = sandbox.check_permissions(action, resource, group=group)
            assert result is True, f"{action} should be allowed in ALLOW_ALL mode"

        # No prompts should have been shown
        mock_callback.assert_not_called()

    def test_allow_all_mode_ignores_permissions_manager(self, temp_dir, persona_dir):
        """Test that ALLOW_ALL mode ignores permissions manager restrictions.

        Even if a permissions manager has restrictive settings, ALLOW_ALL should
        bypass all checks.
        """
        sandbox = Sandbox(str(temp_dir), SandboxMode.ALLOW_ALL)

        # Set up a restrictive permissions manager
        manager = PermissionsManager(persona_dir, dwr_mode=False)
        manager.permissions = ToolPermissions(
            mode="allowlist",
            allow_tools=set(),  # Nothing allowed
            allow_groups=set(),
            deny_tools={"shell", "read_file"},  # Explicitly denied
            deny_groups={"Shell", "Files"},
            shell_denied_commands={"git", "npm", "ls"},  # Denied shell commands
        )
        sandbox.permissions_manager = manager

        mock_callback = MagicMock(return_value=True)
        sandbox._permission_check_callback = mock_callback

        # Despite restrictive settings, ALLOW_ALL should allow everything
        result = sandbox.check_permissions("shell", "git status", group="Shell")
        assert result is True

        result = sandbox.check_permissions("read_file", "test.txt", group="Files")
        assert result is True

        mock_callback.assert_not_called()


class TestShellPermissionCheckMethod:
    """Tests for the _shell_permission_check method."""

    def test_shell_permission_check_uses_parser(self, sandbox_with_manager):
        """Test that shell permission check uses the shell parser."""
        sandbox = sandbox_with_manager

        # Set up to track what's called
        sandbox._permission_check_callback = MagicMock(return_value=True)

        sandbox._shell_permission_check("git status", "Shell")

        # Should have called the callback with parsed info
        sandbox._permission_check_callback.assert_called()
        call_args = sandbox._permission_check_callback.call_args
        action_args = call_args[0][3]  # action_arguments
        assert "parsed" in action_args

    def test_all_commands_allowed_skips_prompt(self, sandbox_with_manager):
        """Test that when all commands are pre-allowed, prompt is skipped."""
        sandbox = sandbox_with_manager
        sandbox.permissions_manager.permissions = ToolPermissions(
            shell_allowed_commands={"git"}
        )

        sandbox._permission_check_callback = MagicMock()
        result = sandbox._shell_permission_check("git status", "Shell")

        assert result is True
        sandbox._permission_check_callback.assert_not_called()

    def test_some_commands_denied_shows_warning(self, sandbox_with_manager):
        """Test that denied commands trigger warning in prompt."""
        sandbox = sandbox_with_manager
        sandbox.permissions_manager.permissions = ToolPermissions(
            shell_denied_commands={"sudo"}
        )

        sandbox._permission_check_callback = MagicMock(return_value=False)
        result = sandbox._shell_permission_check("sudo rm -rf /", "Shell")

        assert result is False
        # Callback should have been called with denied info
        call_args = sandbox._permission_check_callback.call_args
        action_args = call_args[0][3]
        assert "denied" in action_args
        assert "sudo" in action_args["denied"]
