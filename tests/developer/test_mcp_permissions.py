"""Tests for MCP permission filtering in the permissions system."""

import json

from silica.developer.tools.permissions import (
    ToolPermissions,
    PermissionsManager,
    PERMISSIONS_FILE,
)


class TestToolPermissionsMCP:
    """Tests for ToolPermissions MCP-related methods."""

    def test_mcp_tool_allowed_in_allowlist_mode_server_allowed(self):
        """Test MCP tool is allowed when server is in allow list."""
        perms = ToolPermissions(
            mode="allowlist",
            mcp_allowed_servers={"sqlite", "github"},
        )

        assert perms.is_mcp_tool_allowed("sqlite", "query") is True
        assert perms.is_mcp_tool_allowed("sqlite", "insert") is True
        assert perms.is_mcp_tool_allowed("github", "create_issue") is True

    def test_mcp_tool_denied_in_allowlist_mode_server_not_allowed(self):
        """Test MCP tool is denied when server not in allow list."""
        perms = ToolPermissions(
            mode="allowlist",
            mcp_allowed_servers={"sqlite"},
        )

        assert perms.is_mcp_tool_allowed("github", "create_issue") is False
        assert perms.is_mcp_tool_allowed("filesystem", "read") is False

    def test_mcp_tool_allowed_by_specific_tool(self):
        """Test specific tool can be allowed without allowing whole server."""
        perms = ToolPermissions(
            mode="allowlist",
            mcp_allowed_tools={"sqlite:query", "github:list_issues"},
        )

        assert perms.is_mcp_tool_allowed("sqlite", "query") is True
        assert perms.is_mcp_tool_allowed("sqlite", "insert") is False  # Not allowed
        assert perms.is_mcp_tool_allowed("github", "list_issues") is True
        assert perms.is_mcp_tool_allowed("github", "create_issue") is False

    def test_mcp_tool_denied_by_deny_list(self):
        """Test specific tool can be denied even if server is allowed."""
        perms = ToolPermissions(
            mode="allowlist",
            mcp_allowed_servers={"sqlite"},
            mcp_denied_tools={"sqlite:delete"},
        )

        assert perms.is_mcp_tool_allowed("sqlite", "query") is True
        assert perms.is_mcp_tool_allowed("sqlite", "delete") is False  # Denied

    def test_mcp_server_denied_overrides_tool_allow(self):
        """Test server deny overrides specific tool allow."""
        perms = ToolPermissions(
            mode="allowlist",
            mcp_allowed_tools={"sqlite:query"},
            mcp_denied_servers={"sqlite"},
        )

        assert perms.is_mcp_tool_allowed("sqlite", "query") is False

    def test_mcp_denylist_mode_allows_by_default(self):
        """Test denylist mode allows all tools by default."""
        perms = ToolPermissions(mode="denylist")

        assert perms.is_mcp_tool_allowed("sqlite", "query") is True
        assert perms.is_mcp_tool_allowed("github", "create_issue") is True
        assert perms.is_mcp_tool_allowed("anything", "any_tool") is True

    def test_mcp_denylist_mode_denies_specific_server(self):
        """Test denylist mode can deny specific servers."""
        perms = ToolPermissions(
            mode="denylist",
            mcp_denied_servers={"dangerous_server"},
        )

        assert perms.is_mcp_tool_allowed("sqlite", "query") is True
        assert perms.is_mcp_tool_allowed("dangerous_server", "rm_rf") is False

    def test_mcp_denylist_mode_denies_specific_tool(self):
        """Test denylist mode can deny specific tools."""
        perms = ToolPermissions(
            mode="denylist",
            mcp_denied_tools={"sqlite:delete"},
        )

        assert perms.is_mcp_tool_allowed("sqlite", "query") is True
        assert perms.is_mcp_tool_allowed("sqlite", "delete") is False


class TestToolPermissionsMCPServer:
    """Tests for is_mcp_server_allowed method."""

    def test_server_allowed_in_allowlist_mode(self):
        """Test server is allowed when in allow list."""
        perms = ToolPermissions(
            mode="allowlist",
            mcp_allowed_servers={"sqlite"},
        )

        assert perms.is_mcp_server_allowed("sqlite") is True
        assert perms.is_mcp_server_allowed("github") is False

    def test_server_allowed_if_tool_allowed(self):
        """Test server is allowed if it has allowed tools."""
        perms = ToolPermissions(
            mode="allowlist",
            mcp_allowed_tools={"sqlite:query"},
        )

        assert perms.is_mcp_server_allowed("sqlite") is True
        assert perms.is_mcp_server_allowed("github") is False

    def test_server_denied_in_allowlist_mode(self):
        """Test server can be denied in allowlist mode."""
        perms = ToolPermissions(
            mode="allowlist",
            mcp_allowed_servers={"sqlite"},
            mcp_denied_servers={"sqlite"},  # Deny overrides allow
        )

        assert perms.is_mcp_server_allowed("sqlite") is False

    def test_server_allowed_by_default_in_denylist_mode(self):
        """Test all servers allowed by default in denylist mode."""
        perms = ToolPermissions(mode="denylist")

        assert perms.is_mcp_server_allowed("anything") is True

    def test_server_denied_in_denylist_mode(self):
        """Test specific server can be denied in denylist mode."""
        perms = ToolPermissions(
            mode="denylist",
            mcp_denied_servers={"dangerous"},
        )

        assert perms.is_mcp_server_allowed("safe") is True
        assert perms.is_mcp_server_allowed("dangerous") is False


class TestToolPermissionsMCPLoadSave:
    """Tests for loading and saving MCP permissions."""

    def test_save_and_load_mcp_permissions(self, tmp_path):
        """Test MCP permissions round-trip through save/load."""
        perms = ToolPermissions(
            mode="allowlist",
            mcp_allowed_servers={"sqlite", "github"},
            mcp_denied_servers={"dangerous"},
            mcp_allowed_tools={"filesystem:read"},
            mcp_denied_tools={"sqlite:delete"},
        )

        # Save
        perms.save(tmp_path)

        # Verify JSON structure
        with open(tmp_path / PERMISSIONS_FILE) as f:
            data = json.load(f)

        assert "mcp_permissions" in data
        assert set(data["mcp_permissions"]["allowed_servers"]) == {"github", "sqlite"}
        assert set(data["mcp_permissions"]["denied_servers"]) == {"dangerous"}
        assert set(data["mcp_permissions"]["allowed_tools"]) == {"filesystem:read"}
        assert set(data["mcp_permissions"]["denied_tools"]) == {"sqlite:delete"}

        # Load
        loaded = ToolPermissions.load(tmp_path)
        assert loaded is not None
        assert loaded.mcp_allowed_servers == {"sqlite", "github"}
        assert loaded.mcp_denied_servers == {"dangerous"}
        assert loaded.mcp_allowed_tools == {"filesystem:read"}
        assert loaded.mcp_denied_tools == {"sqlite:delete"}

    def test_load_without_mcp_section(self, tmp_path):
        """Test loading old config without MCP section."""
        # Write config without MCP section
        config = {
            "version": 1,
            "mode": "allowlist",
            "allow": {"tools": ["test"], "groups": []},
            "deny": {"tools": [], "groups": []},
            "shell_permissions": {"allowed_commands": [], "denied_commands": []},
        }

        with open(tmp_path / PERMISSIONS_FILE, "w") as f:
            json.dump(config, f)

        # Should load with empty MCP sets
        loaded = ToolPermissions.load(tmp_path)
        assert loaded is not None
        assert loaded.mcp_allowed_servers == set()
        assert loaded.mcp_denied_servers == set()
        assert loaded.mcp_allowed_tools == set()
        assert loaded.mcp_denied_tools == set()


class TestPermissionsManagerMCP:
    """Tests for PermissionsManager MCP-related methods."""

    def test_filter_mcp_tools_dwr_mode(self, tmp_path):
        """Test filter_mcp_tools in DWR mode returns all tools."""
        manager = PermissionsManager(tmp_path, dwr_mode=True)

        tools = [
            {"name": "mcp_sqlite_query", "description": "Query"},
            {"name": "mcp_sqlite_delete", "description": "Delete"},
        ]

        result = manager.filter_mcp_tools(tools, "sqlite")
        assert len(result) == 2

    def test_filter_mcp_tools_no_permissions(self, tmp_path):
        """Test filter_mcp_tools with no permissions file returns all tools (permissive default)."""
        manager = PermissionsManager(tmp_path, dwr_mode=False)

        tools = [{"name": "mcp_sqlite_query", "description": "Query"}]

        result = manager.filter_mcp_tools(tools, "sqlite")
        # No permissions file = allow all tools (permissive default for custom personas)
        assert len(result) == 1

    def test_filter_mcp_tools_allowlist(self, tmp_path):
        """Test filter_mcp_tools with allowlist permissions."""
        # Create permissions file
        perms = ToolPermissions(
            mode="allowlist",
            mcp_allowed_servers={"sqlite"},
            mcp_denied_tools={"sqlite:delete"},
        )
        perms.save(tmp_path)

        manager = PermissionsManager(tmp_path, dwr_mode=False)

        tools = [
            {"name": "mcp_sqlite_query", "description": "Query"},
            {"name": "mcp_sqlite_delete", "description": "Delete"},
            {"name": "mcp_sqlite_insert", "description": "Insert"},
        ]

        result = manager.filter_mcp_tools(tools, "sqlite")

        # query and insert allowed, delete denied
        assert len(result) == 2
        names = {t["name"] for t in result}
        assert "mcp_sqlite_query" in names
        assert "mcp_sqlite_insert" in names
        assert "mcp_sqlite_delete" not in names

    def test_is_mcp_server_allowed_dwr_mode(self, tmp_path):
        """Test is_mcp_server_allowed in DWR mode returns True."""
        manager = PermissionsManager(tmp_path, dwr_mode=True)
        assert manager.is_mcp_server_allowed("any_server") is True

    def test_is_mcp_server_allowed_no_permissions(self, tmp_path):
        """Test is_mcp_server_allowed with no permissions returns False."""
        manager = PermissionsManager(tmp_path, dwr_mode=False)
        assert manager.is_mcp_server_allowed("any_server") is False

    def test_is_mcp_server_allowed_with_permissions(self, tmp_path):
        """Test is_mcp_server_allowed with permissions."""
        perms = ToolPermissions(
            mode="allowlist",
            mcp_allowed_servers={"sqlite"},
        )
        perms.save(tmp_path)

        manager = PermissionsManager(tmp_path, dwr_mode=False)

        assert manager.is_mcp_server_allowed("sqlite") is True
        assert manager.is_mcp_server_allowed("github") is False

    def test_add_mcp_server(self, tmp_path):
        """Test add_mcp_server method."""
        manager = PermissionsManager(tmp_path, dwr_mode=False)

        manager.add_mcp_server("sqlite", allow=True)
        manager.add_mcp_server("dangerous", allow=False)

        assert manager.permissions is not None
        assert "sqlite" in manager.permissions.mcp_allowed_servers
        assert "dangerous" in manager.permissions.mcp_denied_servers

    def test_remove_mcp_server(self, tmp_path):
        """Test remove_mcp_server method."""
        perms = ToolPermissions(
            mcp_allowed_servers={"sqlite"},
            mcp_denied_servers={"dangerous"},
        )
        perms.save(tmp_path)

        manager = PermissionsManager(tmp_path, dwr_mode=False)

        manager.remove_mcp_server("sqlite", from_allow=True)
        manager.remove_mcp_server("dangerous", from_allow=False)

        assert "sqlite" not in manager.permissions.mcp_allowed_servers
        assert "dangerous" not in manager.permissions.mcp_denied_servers

    def test_add_mcp_tool(self, tmp_path):
        """Test add_mcp_tool method."""
        manager = PermissionsManager(tmp_path, dwr_mode=False)

        manager.add_mcp_tool("sqlite", "query", allow=True)
        manager.add_mcp_tool("sqlite", "delete", allow=False)

        assert "sqlite:query" in manager.permissions.mcp_allowed_tools
        assert "sqlite:delete" in manager.permissions.mcp_denied_tools

    def test_remove_mcp_tool(self, tmp_path):
        """Test remove_mcp_tool method."""
        perms = ToolPermissions(
            mcp_allowed_tools={"sqlite:query"},
            mcp_denied_tools={"sqlite:delete"},
        )
        perms.save(tmp_path)

        manager = PermissionsManager(tmp_path, dwr_mode=False)

        manager.remove_mcp_tool("sqlite", "query", from_allow=True)
        manager.remove_mcp_tool("sqlite", "delete", from_allow=False)

        assert "sqlite:query" not in manager.permissions.mcp_allowed_tools
        assert "sqlite:delete" not in manager.permissions.mcp_denied_tools
