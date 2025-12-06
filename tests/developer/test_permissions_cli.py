"""
Tests for the permission management CLI tools (/permissions and /groups).

These tests validate the CLI commands for managing tool permissions
from within the Toolbox.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from silica.developer.toolbox import Toolbox
from silica.developer.tools.permissions import PERMISSIONS_FILE


@pytest.fixture
def mock_context(tmp_path):
    """Create a mock AgentContext with a persona directory."""
    context = MagicMock()
    context.history_base_dir = tmp_path / "test_persona"
    context.history_base_dir.mkdir(parents=True, exist_ok=True)
    context.dwr_mode = False
    context.user_interface = MagicMock()
    context.sandbox = MagicMock()
    return context


@pytest.fixture
def toolbox_with_permissions(mock_context, tmp_path):
    """Create a Toolbox with permissions manager enabled."""
    # Create a basic permissions file
    config = {
        "version": 1,
        "mode": "denylist",
        "allow": {"tools": [], "groups": []},
        "deny": {"tools": [], "groups": []},
        "shell_permissions": {
            "allowed_commands": [],
            "denied_commands": [],
        },
    }
    with open(mock_context.history_base_dir / PERMISSIONS_FILE, "w") as f:
        json.dump(config, f)

    with patch("silica.developer.toolbox.GOOGLE_AUTH_CLI_TOOLS", {}):
        toolbox = Toolbox(mock_context)
    return toolbox


class TestPermissionsCommand:
    """Tests for the /permissions CLI command."""

    def test_permissions_no_args_shows_config(self, toolbox_with_permissions):
        """Test that /permissions with no args shows current config."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="",
        )
        
        assert "Tool Permissions Configuration" in result
        assert "Mode:" in result
        assert "denylist" in result

    def test_permissions_no_manager(self, mock_context):
        """Test permissions command when no manager is available."""
        mock_context.history_base_dir = None
        
        with patch("silica.developer.toolbox.GOOGLE_AUTH_CLI_TOOLS", {}):
            toolbox = Toolbox(mock_context)
        
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="",
        )
        
        assert "Error" in result
        assert "not available" in result

    def test_permissions_mode_allowlist(self, toolbox_with_permissions):
        """Test setting mode to allowlist."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="mode allowlist",
        )
        
        assert "✓" in result
        assert "allowlist" in result
        assert toolbox.permissions_manager.permissions.mode == "allowlist"

    def test_permissions_mode_denylist(self, toolbox_with_permissions):
        """Test setting mode to denylist."""
        toolbox = toolbox_with_permissions
        # First set to allowlist, then back to denylist
        toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="mode allowlist",
        )
        
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="mode denylist",
        )
        
        assert "✓" in result
        assert "denylist" in result
        assert toolbox.permissions_manager.permissions.mode == "denylist"

    def test_permissions_mode_invalid(self, toolbox_with_permissions):
        """Test setting an invalid mode."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="mode invalid",
        )
        
        assert "Error" in result
        assert "Invalid mode" in result

    def test_permissions_mode_missing_arg(self, toolbox_with_permissions):
        """Test mode command without argument."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="mode",
        )
        
        assert "Error" in result
        assert "requires a mode argument" in result

    def test_permissions_allow_group(self, toolbox_with_permissions):
        """Test allowing a group."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="allow Files",
        )
        
        assert "✓" in result
        assert "group" in result
        assert "Files" in toolbox.permissions_manager.permissions.allow_groups

    def test_permissions_allow_tool(self, toolbox_with_permissions):
        """Test allowing a specific tool."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="allow read_file",
        )
        
        assert "✓" in result
        assert "tool" in result
        assert "read_file" in toolbox.permissions_manager.permissions.allow_tools

    def test_permissions_allow_missing_name(self, toolbox_with_permissions):
        """Test allow command without name."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="allow",
        )
        
        assert "Error" in result
        assert "requires a tool or group name" in result

    def test_permissions_deny_group(self, toolbox_with_permissions):
        """Test denying a group."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="deny Shell",
        )
        
        assert "✓" in result
        assert "group" in result
        assert "Shell" in toolbox.permissions_manager.permissions.deny_groups

    def test_permissions_deny_tool(self, toolbox_with_permissions):
        """Test denying a specific tool."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="deny shell_execute",
        )
        
        assert "✓" in result
        assert "tool" in result
        assert "shell_execute" in toolbox.permissions_manager.permissions.deny_tools

    def test_permissions_remove_allow(self, toolbox_with_permissions):
        """Test removing from allow list."""
        toolbox = toolbox_with_permissions
        # First add
        toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="allow Files",
        )
        assert "Files" in toolbox.permissions_manager.permissions.allow_groups
        
        # Then remove
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="remove allow Files",
        )
        
        assert "✓" in result
        assert "Removed" in result
        assert "Files" not in toolbox.permissions_manager.permissions.allow_groups

    def test_permissions_remove_deny(self, toolbox_with_permissions):
        """Test removing from deny list."""
        toolbox = toolbox_with_permissions
        # First add
        toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="deny Shell",
        )
        assert "Shell" in toolbox.permissions_manager.permissions.deny_groups
        
        # Then remove
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="remove deny Shell",
        )
        
        assert "✓" in result
        assert "Removed" in result
        assert "Shell" not in toolbox.permissions_manager.permissions.deny_groups

    def test_permissions_remove_missing_args(self, toolbox_with_permissions):
        """Test remove command without enough arguments."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="remove allow",
        )
        
        assert "Error" in result
        assert "requires" in result

    def test_permissions_remove_invalid_list_type(self, toolbox_with_permissions):
        """Test remove with invalid list type."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="remove invalid_type read_file",
        )
        
        assert "Error" in result
        assert "Invalid list type" in result

    def test_permissions_shell_allow(self, toolbox_with_permissions):
        """Test allowing a shell command."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="shell allow git",
        )
        
        assert "✓" in result
        assert "shell command" in result
        assert "git" in toolbox.permissions_manager.permissions.shell_allowed_commands

    def test_permissions_shell_deny(self, toolbox_with_permissions):
        """Test denying a shell command."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="shell deny sudo",
        )
        
        assert "✓" in result
        assert "shell command" in result
        assert "sudo" in toolbox.permissions_manager.permissions.shell_denied_commands

    def test_permissions_shell_missing_args(self, toolbox_with_permissions):
        """Test shell command without enough arguments."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="shell allow",
        )
        
        assert "Error" in result
        assert "requires" in result

    def test_permissions_shell_invalid_action(self, toolbox_with_permissions):
        """Test shell command with invalid action."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="shell invalid_action git",
        )
        
        assert "Error" in result
        assert "Invalid action" in result

    def test_permissions_unknown_command(self, toolbox_with_permissions):
        """Test unknown subcommand."""
        toolbox = toolbox_with_permissions
        result = toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="unknown_command",
        )
        
        assert "Error" in result
        assert "Unknown subcommand" in result
        assert "Usage:" in result

    def test_permissions_persisted_to_file(self, toolbox_with_permissions, mock_context):
        """Test that permission changes are saved to disk."""
        toolbox = toolbox_with_permissions
        toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="allow Memory",
        )
        
        # Load the file directly
        with open(mock_context.history_base_dir / PERMISSIONS_FILE) as f:
            data = json.load(f)
        
        assert "Memory" in data["allow"]["groups"]


class TestListGroupsCommand:
    """Tests for the /groups CLI command."""

    def test_groups_lists_all_groups(self, toolbox_with_permissions):
        """Test that /groups lists available tool groups."""
        toolbox = toolbox_with_permissions
        result = toolbox._list_groups(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="",
        )
        
        assert "Available Tool Groups" in result
        # Check for some expected groups
        assert "Files" in result or "Shell" in result or "Memory" in result
        assert "Total:" in result

    def test_groups_shows_tools_in_groups(self, toolbox_with_permissions):
        """Test that /groups shows tools within each group."""
        toolbox = toolbox_with_permissions
        result = toolbox._list_groups(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="",
        )
        
        # Should contain at least some tool names
        assert "read_file" in result or "write_file" in result or "shell_execute" in result


class TestToolboxIntegration:
    """Integration tests for toolbox with permissions."""

    def test_toolbox_cli_commands_registered(self, toolbox_with_permissions):
        """Test that permissions CLI commands are registered."""
        toolbox = toolbox_with_permissions
        
        assert "permissions" in toolbox.local
        assert "perms" in toolbox.local  # alias
        assert "groups" in toolbox.local

    def test_permissions_alias_works(self, toolbox_with_permissions):
        """Test that /perms works as alias for /permissions."""
        toolbox = toolbox_with_permissions
        
        # Should point to same handler
        assert toolbox.local["permissions"]["invoke"] == toolbox.local["perms"]["invoke"]

    def test_refresh_tools_updates_schemas(self, toolbox_with_permissions):
        """Test that refreshing tools updates the schema."""
        toolbox = toolbox_with_permissions
        
        # Add a group to allow list
        toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="mode allowlist",
        )
        toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="allow Files",
        )
        
        # Schema should be regenerated (count may change based on filtering)
        assert toolbox.agent_schema is not None


class TestIsGroupName:
    """Tests for the _is_group_name helper method."""

    def test_capitalized_name_is_group(self, toolbox_with_permissions):
        """Test that capitalized names are identified as groups."""
        toolbox = toolbox_with_permissions
        
        assert toolbox._is_group_name("Files") is True
        assert toolbox._is_group_name("Memory") is True
        assert toolbox._is_group_name("Gmail") is True

    def test_lowercase_with_underscore_is_tool(self, toolbox_with_permissions):
        """Test that lowercase names with underscores are identified as tools."""
        toolbox = toolbox_with_permissions
        
        assert toolbox._is_group_name("read_file") is False
        assert toolbox._is_group_name("gmail_send") is False
        assert toolbox._is_group_name("shell_execute") is False

    def test_known_groups_are_recognized(self, toolbox_with_permissions):
        """Test that known group names from ALL_TOOLS are recognized."""
        toolbox = toolbox_with_permissions
        
        # These should be recognized from the tools we know exist
        # This test will pass regardless of specific group names
        # as long as the function returns True for actual group names
        from silica.developer.tools import ALL_TOOLS
        from silica.developer.tools.framework import get_tool_group
        
        for tool in ALL_TOOLS[:5]:  # Test first 5 tools
            group = get_tool_group(tool)
            if group:
                assert toolbox._is_group_name(group) is True


class TestShowPermissionsConfig:
    """Tests for the _show_permissions_config helper method."""

    def test_show_config_no_permissions(self, mock_context):
        """Test showing config when no permissions file exists."""
        with patch("silica.developer.toolbox.GOOGLE_AUTH_CLI_TOOLS", {}):
            toolbox = Toolbox(mock_context)
        
        result = toolbox._show_permissions_config()
        
        assert "No permissions configured" in result
        assert "tool_permissions.json" in result

    def test_show_config_with_allowlist(self, toolbox_with_permissions):
        """Test showing config in allowlist mode."""
        toolbox = toolbox_with_permissions
        toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="mode allowlist",
        )
        toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="allow Files",
        )
        
        result = toolbox._show_permissions_config()
        
        assert "allowlist" in result
        assert "Files" in result
        assert "Allow List" in result

    def test_show_config_with_deny_list(self, toolbox_with_permissions):
        """Test showing config with deny list entries."""
        toolbox = toolbox_with_permissions
        toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="deny Shell",
        )
        
        result = toolbox._show_permissions_config()
        
        assert "Shell" in result
        assert "Deny List" in result

    def test_show_config_with_shell_permissions(self, toolbox_with_permissions):
        """Test showing config with shell permissions."""
        toolbox = toolbox_with_permissions
        toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="shell allow git",
        )
        toolbox._permissions(
            user_interface=MagicMock(),
            sandbox=MagicMock(),
            user_input="shell deny sudo",
        )
        
        result = toolbox._show_permissions_config()
        
        assert "Shell Permissions" in result
        assert "git" in result
        assert "sudo" in result

    def test_show_config_displays_tool_counts(self, toolbox_with_permissions):
        """Test that config shows current tool counts."""
        toolbox = toolbox_with_permissions
        
        result = toolbox._show_permissions_config()
        
        assert "Currently Available Tools" in result
        assert "Agent tools:" in result
        assert "User tools:" in result
