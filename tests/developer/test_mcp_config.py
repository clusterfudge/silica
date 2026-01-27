"""Tests for MCP configuration loading."""

import json


from silica.developer.mcp.config import (
    MCPConfig,
    MCPServerConfig,
    expand_env_vars,
    expand_env_vars_recursive,
    load_mcp_config,
)


class TestExpandEnvVars:
    """Tests for environment variable expansion."""

    def test_simple_var(self, monkeypatch):
        """Test simple ${VAR} expansion."""
        monkeypatch.setenv("TEST_VAR", "hello")
        assert expand_env_vars("${TEST_VAR}") == "hello"

    def test_var_with_text(self, monkeypatch):
        """Test ${VAR} expansion with surrounding text."""
        monkeypatch.setenv("TOKEN", "abc123")
        assert expand_env_vars("Bearer ${TOKEN}") == "Bearer abc123"

    def test_unset_var_empty_string(self, monkeypatch):
        """Test unset var becomes empty string."""
        monkeypatch.delenv("UNSET_VAR", raising=False)
        assert expand_env_vars("${UNSET_VAR}") == ""

    def test_var_with_default(self, monkeypatch):
        """Test ${VAR:-default} syntax."""
        monkeypatch.delenv("UNSET_VAR", raising=False)
        assert expand_env_vars("${UNSET_VAR:-fallback}") == "fallback"

    def test_var_with_default_when_set(self, monkeypatch):
        """Test ${VAR:-default} uses var value when set."""
        monkeypatch.setenv("SET_VAR", "actual")
        assert expand_env_vars("${SET_VAR:-fallback}") == "actual"

    def test_multiple_vars(self, monkeypatch):
        """Test multiple vars in one string."""
        monkeypatch.setenv("HOST", "localhost")
        monkeypatch.setenv("PORT", "8080")
        assert expand_env_vars("${HOST}:${PORT}") == "localhost:8080"

    def test_no_vars(self):
        """Test string with no vars unchanged."""
        assert expand_env_vars("plain text") == "plain text"


class TestExpandEnvVarsRecursive:
    """Tests for recursive environment variable expansion."""

    def test_dict(self, monkeypatch):
        """Test expansion in dictionary values."""
        monkeypatch.setenv("SECRET", "mysecret")
        data = {"key": "${SECRET}", "plain": "value"}
        result = expand_env_vars_recursive(data)
        assert result == {"key": "mysecret", "plain": "value"}

    def test_nested_dict(self, monkeypatch):
        """Test expansion in nested dictionaries."""
        monkeypatch.setenv("TOKEN", "tok123")
        data = {"outer": {"inner": "${TOKEN}"}}
        result = expand_env_vars_recursive(data)
        assert result == {"outer": {"inner": "tok123"}}

    def test_list(self, monkeypatch):
        """Test expansion in list items."""
        monkeypatch.setenv("ITEM", "value")
        data = ["${ITEM}", "static"]
        result = expand_env_vars_recursive(data)
        assert result == ["value", "static"]


class TestMCPServerConfig:
    """Tests for MCPServerConfig dataclass."""

    def test_from_dict_minimal(self):
        """Test creating server config with minimal fields."""
        data = {"command": "python", "args": ["server.py"]}
        cfg = MCPServerConfig.from_dict("myserver", data)
        assert cfg.name == "myserver"
        assert cfg.command == "python"
        assert cfg.args == ["server.py"]
        assert cfg.enabled is True
        assert cfg.cache is True

    def test_from_dict_full(self):
        """Test creating server config with all fields."""
        data = {
            "command": "uvx",
            "args": ["mcp-server-sqlite"],
            "env": {"DB_PATH": "/tmp/db.sqlite"},
            "enabled": False,
            "cache": False,
            "setup_command": "uvx",
            "setup_args": ["mcp-server-sqlite", "--auth"],
            "credentials_path": "${HOME}/.config/mcp/creds.json",
        }
        cfg = MCPServerConfig.from_dict("sqlite", data)
        assert cfg.name == "sqlite"
        assert cfg.command == "uvx"
        assert cfg.env == {"DB_PATH": "/tmp/db.sqlite"}
        assert cfg.enabled is False
        assert cfg.cache is False
        assert cfg.setup_command == "uvx"
        assert cfg.setup_args == ["mcp-server-sqlite", "--auth"]
        assert cfg.credentials_path == "${HOME}/.config/mcp/creds.json"

    def test_needs_setup_no_path(self):
        """Test needs_setup returns False when no credentials_path."""
        cfg = MCPServerConfig(name="test", command="cmd")
        assert cfg.needs_setup() is False

    def test_needs_setup_path_exists(self, tmp_path):
        """Test needs_setup returns False when credentials exist."""
        creds_file = tmp_path / "creds.json"
        creds_file.write_text("{}")
        cfg = MCPServerConfig(
            name="test", command="cmd", credentials_path=str(creds_file)
        )
        assert cfg.needs_setup() is False

    def test_needs_setup_path_missing(self, tmp_path):
        """Test needs_setup returns True when credentials don't exist."""
        cfg = MCPServerConfig(
            name="test", command="cmd", credentials_path=str(tmp_path / "missing.json")
        )
        assert cfg.needs_setup() is True

    def test_has_setup_command(self):
        """Test has_setup_command returns correct value."""
        cfg = MCPServerConfig(name="test", command="cmd")
        assert cfg.has_setup_command() is False

        cfg = MCPServerConfig(name="test", command="cmd", setup_command="setup")
        assert cfg.has_setup_command() is True


class TestMCPConfig:
    """Tests for MCPConfig dataclass."""

    def test_from_dict(self):
        """Test creating config from dict."""
        data = {
            "servers": {
                "sqlite": {"command": "uvx", "args": ["mcp-server-sqlite"]},
                "github": {"command": "npx", "args": ["-y", "mcp-server-github"]},
            }
        }
        cfg = MCPConfig.from_dict(data)
        assert len(cfg.servers) == 2
        assert "sqlite" in cfg.servers
        assert "github" in cfg.servers

    def test_get_enabled_servers(self):
        """Test filtering to only enabled servers."""
        data = {
            "servers": {
                "enabled": {"command": "cmd1", "enabled": True},
                "disabled": {"command": "cmd2", "enabled": False},
            }
        }
        cfg = MCPConfig.from_dict(data)
        enabled = cfg.get_enabled_servers()
        assert len(enabled) == 1
        assert "enabled" in enabled

    def test_merge_with(self):
        """Test merging two configs."""
        base = MCPConfig.from_dict(
            {
                "servers": {
                    "sqlite": {"command": "uvx", "args": ["v1"]},
                    "only_base": {"command": "base"},
                }
            }
        )
        override = MCPConfig.from_dict(
            {
                "servers": {
                    "sqlite": {"command": "uvx", "args": ["v2"]},
                    "only_override": {"command": "override"},
                }
            }
        )
        merged = base.merge_with(override)
        # Override wins for sqlite
        assert merged.servers["sqlite"].args == ["v2"]
        # Both unique servers present
        assert "only_base" in merged.servers
        assert "only_override" in merged.servers

    def test_from_file(self, tmp_path, monkeypatch):
        """Test loading config from JSON file."""
        monkeypatch.setenv("TEST_TOKEN", "secret123")
        config_file = tmp_path / "mcp_servers.json"
        config_file.write_text(
            json.dumps(
                {
                    "servers": {
                        "myserver": {
                            "command": "python",
                            "args": ["server.py"],
                            "env": {"TOKEN": "${TEST_TOKEN}"},
                        }
                    }
                }
            )
        )
        cfg = MCPConfig.from_file(config_file)
        assert cfg.servers["myserver"].env["TOKEN"] == "secret123"


class TestLoadMcpConfig:
    """Tests for the load_mcp_config function."""

    def test_no_config_files(self, tmp_path):
        """Test loading when no config files exist."""
        cfg = load_mcp_config(
            project_root=tmp_path, persona=None, silica_dir=tmp_path / ".silica"
        )
        assert len(cfg.servers) == 0

    def test_global_config_only(self, tmp_path):
        """Test loading global config only."""
        silica_dir = tmp_path / ".silica"
        silica_dir.mkdir()
        (silica_dir / "mcp_servers.json").write_text(
            json.dumps({"servers": {"global_server": {"command": "global"}}})
        )
        cfg = load_mcp_config(silica_dir=silica_dir)
        assert "global_server" in cfg.servers

    def test_persona_overrides_global(self, tmp_path):
        """Test persona config overrides global."""
        silica_dir = tmp_path / ".silica"
        silica_dir.mkdir()
        (silica_dir / "mcp_servers.json").write_text(
            json.dumps({"servers": {"server": {"command": "global", "cache": True}}})
        )
        persona_dir = silica_dir / "personas" / "test_persona"
        persona_dir.mkdir(parents=True)
        (persona_dir / "mcp_servers.json").write_text(
            json.dumps({"servers": {"server": {"command": "persona", "cache": False}}})
        )
        cfg = load_mcp_config(persona="test_persona", silica_dir=silica_dir)
        assert cfg.servers["server"].command == "persona"
        assert cfg.servers["server"].cache is False

    def test_project_overrides_all(self, tmp_path):
        """Test project config has highest precedence."""
        silica_dir = tmp_path / ".silica"
        silica_dir.mkdir()
        (silica_dir / "mcp_servers.json").write_text(
            json.dumps({"servers": {"server": {"command": "global"}}})
        )
        project_root = tmp_path / "project"
        project_silica = project_root / ".silica"
        project_silica.mkdir(parents=True)
        (project_silica / "mcp_servers.json").write_text(
            json.dumps({"servers": {"server": {"command": "project"}}})
        )
        cfg = load_mcp_config(project_root=project_root, silica_dir=silica_dir)
        assert cfg.servers["server"].command == "project"

    def test_invalid_json_gracefully_handled(self, tmp_path):
        """Test that invalid JSON is handled gracefully."""
        silica_dir = tmp_path / ".silica"
        silica_dir.mkdir()
        (silica_dir / "mcp_servers.json").write_text("not valid json{")
        # Should not raise, just return empty config
        cfg = load_mcp_config(silica_dir=silica_dir)
        assert len(cfg.servers) == 0
