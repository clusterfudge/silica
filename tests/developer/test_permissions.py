"""
Tests for the tool permissions system.

This test suite validates the ToolPermissions dataclass and PermissionsManager class
for filtering tools based on per-persona configuration.
"""

import json
from unittest.mock import MagicMock

import pytest

from silica.developer.tools.permissions import (
    PERMISSIONS_FILE,
    PermissionsManager,
    ToolPermissions,
)


class TestToolPermissionsLoad:
    """Tests for ToolPermissions.load() class method."""

    def test_load_missing_file_returns_none(self, tmp_path):
        """Test that load returns None when permissions file doesn't exist."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        result = ToolPermissions.load(persona_dir)
        assert result is None

    def test_load_valid_json(self, tmp_path):
        """Test that load correctly parses valid JSON."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        config = {
            "version": 1,
            "mode": "allowlist",
            "allow": {
                "tools": ["read_file", "write_file"],
                "groups": ["Files", "Memory"],
            },
            "deny": {"tools": ["dangerous_tool"], "groups": ["Shell"]},
            "shell_permissions": {
                "allowed_commands": ["git", "ls"],
                "denied_commands": ["sudo", "rm"],
            },
        }

        with open(persona_dir / PERMISSIONS_FILE, "w") as f:
            json.dump(config, f)

        result = ToolPermissions.load(persona_dir)

        assert result is not None
        assert result.version == 1
        assert result.mode == "allowlist"
        assert result.allow_tools == {"read_file", "write_file"}
        assert result.allow_groups == {"Files", "Memory"}
        assert result.deny_tools == {"dangerous_tool"}
        assert result.deny_groups == {"Shell"}
        assert result.shell_allowed_commands == {"git", "ls"}
        assert result.shell_denied_commands == {"sudo", "rm"}

    def test_load_invalid_json_returns_none(self, tmp_path):
        """Test that load returns None for invalid JSON."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        with open(persona_dir / PERMISSIONS_FILE, "w") as f:
            f.write("{ this is not valid json }")

        result = ToolPermissions.load(persona_dir)
        assert result is None

    def test_load_empty_json_uses_defaults(self, tmp_path):
        """Test that load uses defaults for missing fields."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        with open(persona_dir / PERMISSIONS_FILE, "w") as f:
            json.dump({}, f)

        result = ToolPermissions.load(persona_dir)

        assert result is not None
        assert result.version == 1  # Default version
        assert result.mode == "allowlist"  # Default mode
        assert result.allow_tools == set()
        assert result.allow_groups == set()
        assert result.deny_tools == set()
        assert result.deny_groups == set()

    def test_load_partial_config(self, tmp_path):
        """Test that load handles partial config correctly."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        config = {
            "mode": "denylist",
            "deny": {"tools": ["rm_rf"], "groups": []},
        }

        with open(persona_dir / PERMISSIONS_FILE, "w") as f:
            json.dump(config, f)

        result = ToolPermissions.load(persona_dir)

        assert result is not None
        assert result.mode == "denylist"
        assert result.deny_tools == {"rm_rf"}
        assert result.allow_tools == set()


class TestToolPermissionsSave:
    """Tests for ToolPermissions.save() method."""

    def test_save_creates_correct_json(self, tmp_path):
        """Test that save creates a properly formatted JSON file."""
        persona_dir = tmp_path / "test_persona"
        # Note: save should create the directory if it doesn't exist

        permissions = ToolPermissions(
            version=1,
            mode="allowlist",
            allow_tools={"read_file", "write_file"},
            allow_groups={"Files", "Memory"},
            deny_tools={"dangerous_tool"},
            deny_groups={"Shell"},
            shell_allowed_commands={"git", "ls"},
            shell_denied_commands={"sudo", "rm"},
        )

        permissions.save(persona_dir)

        # Verify file exists
        assert (persona_dir / PERMISSIONS_FILE).exists()

        # Load and verify content
        with open(persona_dir / PERMISSIONS_FILE, "r") as f:
            data = json.load(f)

        assert data["version"] == 1
        assert data["mode"] == "allowlist"
        assert sorted(data["allow"]["tools"]) == ["read_file", "write_file"]
        assert sorted(data["allow"]["groups"]) == ["Files", "Memory"]
        assert data["deny"]["tools"] == ["dangerous_tool"]
        assert data["deny"]["groups"] == ["Shell"]
        assert sorted(data["shell_permissions"]["allowed_commands"]) == ["git", "ls"]
        assert sorted(data["shell_permissions"]["denied_commands"]) == ["rm", "sudo"]

    def test_save_creates_directory_if_missing(self, tmp_path):
        """Test that save creates persona directory if it doesn't exist."""
        persona_dir = tmp_path / "new_persona"
        assert not persona_dir.exists()

        permissions = ToolPermissions()
        permissions.save(persona_dir)

        assert persona_dir.exists()
        assert (persona_dir / PERMISSIONS_FILE).exists()

    def test_save_overwrites_existing(self, tmp_path):
        """Test that save overwrites existing config."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        # Write initial config
        initial = ToolPermissions(mode="allowlist", allow_tools={"tool1"})
        initial.save(persona_dir)

        # Overwrite with new config
        new = ToolPermissions(mode="denylist", deny_tools={"tool2"})
        new.save(persona_dir)

        # Verify new content
        loaded = ToolPermissions.load(persona_dir)
        assert loaded.mode == "denylist"
        assert loaded.deny_tools == {"tool2"}
        assert loaded.allow_tools == set()


class TestToolPermissionsIsToolAllowed:
    """Tests for ToolPermissions.is_tool_allowed() method."""

    def test_allowlist_mode_allowed_tool(self):
        """Test allowlist mode with an allowed tool."""
        permissions = ToolPermissions(
            mode="allowlist",
            allow_tools={"read_file", "write_file"},
            allow_groups=set(),
        )

        assert permissions.is_tool_allowed("read_file") is True
        assert permissions.is_tool_allowed("write_file") is True

    def test_allowlist_mode_denied_tool(self):
        """Test allowlist mode with a non-allowed tool."""
        permissions = ToolPermissions(
            mode="allowlist",
            allow_tools={"read_file"},
            allow_groups=set(),
        )

        assert permissions.is_tool_allowed("shell_execute") is False
        assert permissions.is_tool_allowed("gmail_send") is False

    def test_allowlist_mode_allowed_by_group(self):
        """Test allowlist mode where tool is allowed by group membership."""
        permissions = ToolPermissions(
            mode="allowlist",
            allow_tools=set(),
            allow_groups={"Files", "Memory"},
        )

        # Tool in allowed group
        assert permissions.is_tool_allowed("read_file", group="Files") is True
        # Tool in another allowed group
        assert permissions.is_tool_allowed("search_memory", group="Memory") is True
        # Tool not in any allowed group
        assert permissions.is_tool_allowed("shell_execute", group="Shell") is False

    def test_allowlist_mode_deny_list_overrides_allow(self):
        """Test that deny list takes precedence over allow list in allowlist mode."""
        permissions = ToolPermissions(
            mode="allowlist",
            allow_tools={"read_file", "write_file", "dangerous_tool"},
            allow_groups=set(),
            deny_tools={"dangerous_tool"},
        )

        assert permissions.is_tool_allowed("read_file") is True
        assert permissions.is_tool_allowed("dangerous_tool") is False

    def test_allowlist_mode_deny_group_overrides_allow(self):
        """Test that deny_groups takes precedence in allowlist mode."""
        permissions = ToolPermissions(
            mode="allowlist",
            allow_tools=set(),
            allow_groups={"Shell"},
            deny_groups={"Shell"},
        )

        # Group is both allowed and denied - deny wins
        assert permissions.is_tool_allowed("shell_execute", group="Shell") is False

    def test_denylist_mode_allowed_tool(self):
        """Test denylist mode allows tools by default."""
        permissions = ToolPermissions(
            mode="denylist",
            allow_tools=set(),
            allow_groups=set(),
            deny_tools=set(),
            deny_groups=set(),
        )

        # Everything allowed when nothing is denied
        assert permissions.is_tool_allowed("read_file") is True
        assert permissions.is_tool_allowed("shell_execute") is True
        assert permissions.is_tool_allowed("gmail_send") is True

    def test_denylist_mode_denied_tool(self):
        """Test denylist mode denies specified tools."""
        permissions = ToolPermissions(
            mode="denylist",
            deny_tools={"dangerous_tool", "shell_execute"},
        )

        assert permissions.is_tool_allowed("dangerous_tool") is False
        assert permissions.is_tool_allowed("shell_execute") is False
        assert permissions.is_tool_allowed("read_file") is True

    def test_denylist_mode_denied_group(self):
        """Test denylist mode denies by group."""
        permissions = ToolPermissions(
            mode="denylist",
            deny_groups={"Shell", "Webcam"},
        )

        assert permissions.is_tool_allowed("shell_execute", group="Shell") is False
        assert permissions.is_tool_allowed("webcam_snapshot", group="Webcam") is False
        assert permissions.is_tool_allowed("read_file", group="Files") is True

    def test_denylist_mode_ignores_allow_lists(self):
        """Test that denylist mode ignores allow lists entirely."""
        permissions = ToolPermissions(
            mode="denylist",
            allow_tools={"specific_tool"},  # Should be ignored
            allow_groups={"SpecificGroup"},  # Should be ignored
            deny_tools=set(),
            deny_groups=set(),
        )

        # All tools allowed regardless of allow lists
        assert permissions.is_tool_allowed("any_tool") is True
        assert permissions.is_tool_allowed("other_tool", group="AnyGroup") is True

    def test_no_group_provided(self):
        """Test behavior when no group is provided."""
        permissions = ToolPermissions(
            mode="allowlist",
            allow_tools=set(),
            allow_groups={"Files"},
        )

        # Without group, only tool name is checked
        assert permissions.is_tool_allowed("read_file") is False
        # With group, allowed
        assert permissions.is_tool_allowed("read_file", group="Files") is True


class TestPermissionsManagerFilterTools:
    """Tests for PermissionsManager.filter_tools() method."""

    def _create_mock_tool(self, name: str, group: str = None):
        """Create a mock tool function."""
        tool = MagicMock()
        tool.__name__ = name
        tool._group = group
        return tool

    def test_dwr_mode_returns_all_tools(self, tmp_path):
        """Test that dwr_mode=True returns all tools unchanged."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        # Even with restrictive permissions file
        config = {"mode": "allowlist", "allow": {"tools": [], "groups": []}}
        with open(persona_dir / PERMISSIONS_FILE, "w") as f:
            json.dump(config, f)

        manager = PermissionsManager(persona_dir, dwr_mode=True)

        tools = [
            self._create_mock_tool("read_file", "Files"),
            self._create_mock_tool("shell_execute", "Shell"),
        ]

        result = manager.filter_tools(tools)
        assert len(result) == 2

    def test_no_config_file_returns_empty_list(self, tmp_path):
        """Test that missing config file returns empty list."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()
        # No permissions file created

        manager = PermissionsManager(persona_dir, dwr_mode=False)

        tools = [
            self._create_mock_tool("read_file", "Files"),
            self._create_mock_tool("shell_execute", "Shell"),
        ]

        result = manager.filter_tools(tools)
        assert len(result) == 0

    def test_allowlist_config_filters_correctly(self, tmp_path):
        """Test that allowlist mode filters tools correctly."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        config = {
            "mode": "allowlist",
            "allow": {"tools": ["read_file"], "groups": ["Memory"]},
            "deny": {"tools": [], "groups": []},
        }
        with open(persona_dir / PERMISSIONS_FILE, "w") as f:
            json.dump(config, f)

        manager = PermissionsManager(persona_dir, dwr_mode=False)

        tools = [
            self._create_mock_tool("read_file", "Files"),
            self._create_mock_tool("search_memory", "Memory"),
            self._create_mock_tool("shell_execute", "Shell"),
        ]

        result = manager.filter_tools(tools)
        result_names = [t.__name__ for t in result]

        assert "read_file" in result_names  # Explicitly allowed
        assert "search_memory" in result_names  # Group allowed
        assert "shell_execute" not in result_names  # Not allowed


class TestPermissionsManagerFilterUserTools:
    """Tests for PermissionsManager.filter_user_tools() method."""

    def _create_mock_discovered_tool(self, name: str, group: str):
        """Create a mock DiscoveredTool."""
        tool = MagicMock()
        tool.name = name
        tool.group = group
        tool.file_stem = group  # Usually same as group for user tools
        return tool

    def test_dwr_mode_returns_all_user_tools(self, tmp_path):
        """Test that dwr_mode returns all user tools."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        manager = PermissionsManager(persona_dir, dwr_mode=True)

        tools = {
            "weather_get": self._create_mock_discovered_tool("weather_get", "weather"),
            "gmail_search": self._create_mock_discovered_tool("gmail_search", "gmail"),
        }

        result = manager.filter_user_tools(tools)
        assert len(result) == 2

    def test_no_config_returns_empty_dict(self, tmp_path):
        """Test that missing config returns empty dict."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        manager = PermissionsManager(persona_dir, dwr_mode=False)

        tools = {
            "weather_get": self._create_mock_discovered_tool("weather_get", "weather"),
        }

        result = manager.filter_user_tools(tools)
        assert len(result) == 0

    def test_filters_user_tools_by_name_and_group(self, tmp_path):
        """Test filtering user tools by name and group."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        config = {
            "mode": "allowlist",
            "allow": {"tools": ["specific_tool"], "groups": ["weather"]},
            "deny": {"tools": [], "groups": []},
        }
        with open(persona_dir / PERMISSIONS_FILE, "w") as f:
            json.dump(config, f)

        manager = PermissionsManager(persona_dir, dwr_mode=False)

        tools = {
            "weather_get": self._create_mock_discovered_tool("weather_get", "weather"),
            "specific_tool": self._create_mock_discovered_tool(
                "specific_tool", "other"
            ),
            "blocked_tool": self._create_mock_discovered_tool(
                "blocked_tool", "blocked"
            ),
        }

        result = manager.filter_user_tools(tools)

        assert "weather_get" in result  # Group allowed
        assert "specific_tool" in result  # Tool allowed
        assert "blocked_tool" not in result  # Not allowed


class TestPermissionsManagerMutationMethods:
    """Tests for PermissionsManager mutation methods."""

    def test_add_to_allow_tool(self, tmp_path):
        """Test adding a tool to allow list."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        manager = PermissionsManager(persona_dir, dwr_mode=False)

        # Initially no permissions
        assert manager.permissions is None

        manager.add_to_allow(tool_name="read_file")

        assert manager.permissions is not None
        assert "read_file" in manager.permissions.allow_tools

    def test_add_to_allow_group(self, tmp_path):
        """Test adding a group to allow list."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        manager = PermissionsManager(persona_dir, dwr_mode=False)
        manager.add_to_allow(group="Files")

        assert manager.permissions is not None
        assert "Files" in manager.permissions.allow_groups

    def test_add_to_deny_tool(self, tmp_path):
        """Test adding a tool to deny list."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        manager = PermissionsManager(persona_dir, dwr_mode=False)
        manager.add_to_deny(tool_name="dangerous_tool")

        assert manager.permissions is not None
        assert "dangerous_tool" in manager.permissions.deny_tools
        # Note: when creating new permissions via add_to_deny, mode defaults to denylist
        assert manager.permissions.mode == "denylist"

    def test_add_to_deny_group(self, tmp_path):
        """Test adding a group to deny list."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        manager = PermissionsManager(persona_dir, dwr_mode=False)
        manager.add_to_deny(group="Shell")

        assert manager.permissions is not None
        assert "Shell" in manager.permissions.deny_groups

    def test_remove_from_allow(self, tmp_path):
        """Test removing from allow list."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        config = {
            "mode": "allowlist",
            "allow": {"tools": ["read_file", "write_file"], "groups": ["Files"]},
            "deny": {"tools": [], "groups": []},
        }
        with open(persona_dir / PERMISSIONS_FILE, "w") as f:
            json.dump(config, f)

        manager = PermissionsManager(persona_dir, dwr_mode=False)

        manager.remove_from_allow(tool_name="read_file")
        manager.remove_from_allow(group="Files")

        assert "read_file" not in manager.permissions.allow_tools
        assert "write_file" in manager.permissions.allow_tools
        assert "Files" not in manager.permissions.allow_groups

    def test_remove_from_deny(self, tmp_path):
        """Test removing from deny list."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        config = {
            "mode": "denylist",
            "allow": {"tools": [], "groups": []},
            "deny": {"tools": ["dangerous"], "groups": ["Shell"]},
        }
        with open(persona_dir / PERMISSIONS_FILE, "w") as f:
            json.dump(config, f)

        manager = PermissionsManager(persona_dir, dwr_mode=False)

        manager.remove_from_deny(tool_name="dangerous")
        manager.remove_from_deny(group="Shell")

        assert "dangerous" not in manager.permissions.deny_tools
        assert "Shell" not in manager.permissions.deny_groups

    def test_set_mode(self, tmp_path):
        """Test setting permission mode."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        manager = PermissionsManager(persona_dir, dwr_mode=False)
        manager.set_mode("denylist")

        assert manager.permissions is not None
        assert manager.permissions.mode == "denylist"

        manager.set_mode("allowlist")
        assert manager.permissions.mode == "allowlist"

    def test_set_mode_invalid_raises_error(self, tmp_path):
        """Test that setting invalid mode raises ValueError."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        manager = PermissionsManager(persona_dir, dwr_mode=False)

        with pytest.raises(ValueError) as exc_info:
            manager.set_mode("invalid_mode")

        assert "invalid_mode" in str(exc_info.value)

    def test_add_shell_command_allow(self, tmp_path):
        """Test adding shell command to allow list."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        manager = PermissionsManager(persona_dir, dwr_mode=False)
        manager.add_shell_command("git", allow=True)

        assert manager.permissions is not None
        assert "git" in manager.permissions.shell_allowed_commands

    def test_add_shell_command_deny(self, tmp_path):
        """Test adding shell command to deny list."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        manager = PermissionsManager(persona_dir, dwr_mode=False)
        manager.add_shell_command("sudo", allow=False)

        assert manager.permissions is not None
        assert "sudo" in manager.permissions.shell_denied_commands

    def test_remove_shell_command(self, tmp_path):
        """Test removing shell command from lists."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        config = {
            "mode": "allowlist",
            "allow": {"tools": [], "groups": []},
            "deny": {"tools": [], "groups": []},
            "shell_permissions": {
                "allowed_commands": ["git", "ls"],
                "denied_commands": ["sudo", "rm"],
            },
        }
        with open(persona_dir / PERMISSIONS_FILE, "w") as f:
            json.dump(config, f)

        manager = PermissionsManager(persona_dir, dwr_mode=False)

        manager.remove_shell_command("git", from_allow=True)
        manager.remove_shell_command("sudo", from_allow=False)

        assert "git" not in manager.permissions.shell_allowed_commands
        assert "ls" in manager.permissions.shell_allowed_commands
        assert "sudo" not in manager.permissions.shell_denied_commands
        assert "rm" in manager.permissions.shell_denied_commands

    def test_save_persists_changes(self, tmp_path):
        """Test that save() persists mutations to disk."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        manager = PermissionsManager(persona_dir, dwr_mode=False)
        manager.add_to_allow(tool_name="read_file")
        manager.add_to_allow(group="Files")
        manager.save()

        # Create new manager and verify changes persisted
        manager2 = PermissionsManager(persona_dir, dwr_mode=False)
        assert "read_file" in manager2.permissions.allow_tools
        assert "Files" in manager2.permissions.allow_groups


class TestPermissionsManagerEdgeCases:
    """Tests for edge cases in PermissionsManager."""

    def test_mutations_on_none_permissions_safe(self, tmp_path):
        """Test that remove operations on None permissions are safe."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        manager = PermissionsManager(persona_dir, dwr_mode=False)
        assert manager.permissions is None

        # These should not raise
        manager.remove_from_allow(tool_name="nonexistent")
        manager.remove_from_allow(group="Nonexistent")
        manager.remove_from_deny(tool_name="nonexistent")
        manager.remove_from_deny(group="Nonexistent")
        manager.remove_shell_command("nonexistent", from_allow=True)
        manager.remove_shell_command("nonexistent", from_allow=False)

        # Still None
        assert manager.permissions is None

    def test_filter_tools_with_real_tool_decorator(self, tmp_path):
        """Test filter_tools works with real @tool decorated functions."""
        from silica.developer.context import AgentContext
        from silica.developer.tools.framework import tool

        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        config = {
            "mode": "allowlist",
            "allow": {"tools": [], "groups": ["TestGroup"]},
            "deny": {"tools": [], "groups": []},
        }
        with open(persona_dir / PERMISSIONS_FILE, "w") as f:
            json.dump(config, f)

        # Create real tool functions
        @tool(group="TestGroup")
        def allowed_tool(context: AgentContext):
            """An allowed tool."""
            return "allowed"

        @tool(group="OtherGroup")
        def blocked_tool(context: AgentContext):
            """A blocked tool."""
            return "blocked"

        @tool  # No group
        def ungrouped_tool(context: AgentContext):
            """A tool without a group."""
            return "ungrouped"

        manager = PermissionsManager(persona_dir, dwr_mode=False)
        tools = [allowed_tool, blocked_tool, ungrouped_tool]

        result = manager.filter_tools(tools)
        result_names = [t.__name__ for t in result]

        assert "allowed_tool" in result_names
        assert "blocked_tool" not in result_names
        assert "ungrouped_tool" not in result_names

    def test_empty_permissions_allowlist_blocks_all(self, tmp_path):
        """Test that empty allowlist permissions blocks all tools."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        # Empty allowlist - nothing allowed
        config = {
            "mode": "allowlist",
            "allow": {"tools": [], "groups": []},
            "deny": {"tools": [], "groups": []},
        }
        with open(persona_dir / PERMISSIONS_FILE, "w") as f:
            json.dump(config, f)

        manager = PermissionsManager(persona_dir, dwr_mode=False)

        mock_tool = MagicMock()
        mock_tool.__name__ = "any_tool"
        mock_tool._group = "AnyGroup"

        result = manager.filter_tools([mock_tool])
        assert len(result) == 0

    def test_empty_permissions_denylist_allows_all(self, tmp_path):
        """Test that empty denylist permissions allows all tools."""
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        # Empty denylist - everything allowed
        config = {
            "mode": "denylist",
            "allow": {"tools": [], "groups": []},
            "deny": {"tools": [], "groups": []},
        }
        with open(persona_dir / PERMISSIONS_FILE, "w") as f:
            json.dump(config, f)

        manager = PermissionsManager(persona_dir, dwr_mode=False)

        mock_tool = MagicMock()
        mock_tool.__name__ = "any_tool"
        mock_tool._group = "AnyGroup"

        result = manager.filter_tools([mock_tool])
        assert len(result) == 1
