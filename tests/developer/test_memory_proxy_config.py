"""Tests for memory proxy configuration management."""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from silica.developer.memory.proxy_config import MemoryProxyConfig


@pytest.fixture
def temp_config_dir():
    """Create a temporary directory for config files."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def config(temp_config_dir):
    """Create a memory proxy config with temporary directory."""
    config_path = temp_config_dir / "memory_proxy.json"
    return MemoryProxyConfig(config_path=config_path)


def test_default_config(config):
    """Test default configuration values."""
    assert config.is_configured is False
    assert config.is_globally_enabled is False
    assert config.remote_url == ""
    assert config.auth_token == ""


def test_setup(config):
    """Test setting up memory proxy configuration."""
    config.setup(
        remote_url="https://memory-proxy.example.com",
        auth_token="test-token-12345",
        enable=True,
    )

    assert config.is_configured is True
    assert config.is_globally_enabled is True
    assert config.remote_url == "https://memory-proxy.example.com"
    assert config.auth_token == "test-token-12345"


def test_setup_removes_trailing_slash(config):
    """Test that setup removes trailing slash from URL."""
    config.setup(
        remote_url="https://memory-proxy.example.com/",
        auth_token="test-token",
    )

    assert config.remote_url == "https://memory-proxy.example.com"


def test_setup_persists_to_disk(config):
    """Test that configuration is saved to disk."""
    config.setup(
        remote_url="https://memory-proxy.example.com",
        auth_token="test-token",
    )

    # Create new config instance to load from disk
    config2 = MemoryProxyConfig(config_path=config.config_path)

    assert config2.remote_url == "https://memory-proxy.example.com"
    assert config2.auth_token == "test-token"


def test_set_global_enabled(config):
    """Test setting global enabled state."""
    config.setup("https://test.com", "token")

    config.set_global_enabled(False)
    assert config.is_globally_enabled is False

    config.set_global_enabled(True)
    assert config.is_globally_enabled is True


def test_persona_enabled_default(config):
    """Test that persona is enabled by default when globally enabled."""
    config.setup("https://test.com", "token", enable=True)

    # Persona not explicitly configured should default to enabled
    assert config.is_persona_enabled("default") is True
    assert config.is_persona_enabled("new-persona") is True


def test_persona_enabled_when_globally_disabled(config):
    """Test that persona is disabled when globally disabled."""
    config.setup("https://test.com", "token", enable=False)

    # Even if persona would be enabled, global disabled overrides
    assert config.is_persona_enabled("default") is False


def test_set_persona_enabled(config):
    """Test enabling/disabling specific personas."""
    config.setup("https://test.com", "token", enable=True)

    config.set_persona_enabled("default", False)
    assert config.is_persona_enabled("default") is False

    config.set_persona_enabled("default", True)
    assert config.is_persona_enabled("default") is True


def test_get_last_sync_none(config):
    """Test getting last sync when never synced."""
    assert config.get_last_sync("default") is None


def test_set_and_get_last_sync(config):
    """Test setting and getting last sync timestamp."""
    now = datetime.now(timezone.utc)

    config.set_last_sync("default", now)

    last_sync = config.get_last_sync("default")
    assert last_sync is not None
    # Compare timestamps with some tolerance for precision
    assert abs((last_sync - now).total_seconds()) < 1


def test_set_last_sync_defaults_to_now(config):
    """Test that set_last_sync defaults to current time."""
    before = datetime.now(timezone.utc)
    config.set_last_sync("default")
    after = datetime.now(timezone.utc)

    last_sync = config.get_last_sync("default")
    assert last_sync is not None
    assert before <= last_sync <= after


def test_set_last_sync_persists(config):
    """Test that last sync timestamp persists to disk."""
    timestamp = datetime.now(timezone.utc)
    config.set_last_sync("default", timestamp)

    # Load from disk
    config2 = MemoryProxyConfig(config_path=config.config_path)
    last_sync = config2.get_last_sync("default")

    assert last_sync is not None
    assert abs((last_sync - timestamp).total_seconds()) < 1


def test_get_persona_config(config):
    """Test getting all configuration for a persona."""
    config.setup("https://test.com", "token")
    config.set_persona_enabled("default", False)
    config.set_last_sync("default")

    persona_config = config.get_persona_config("default")

    assert persona_config["sync_enabled"] is False
    assert "last_sync" in persona_config


def test_get_persona_config_nonexistent(config):
    """Test getting config for non-existent persona returns empty dict."""
    persona_config = config.get_persona_config("nonexistent")
    assert persona_config == {}


def test_get_all_personas(config):
    """Test getting list of all configured personas."""
    config.setup("https://test.com", "token")
    config.set_persona_enabled("default", True)
    config.set_persona_enabled("coding-agent", False)

    personas = config.get_all_personas()

    assert len(personas) == 2
    assert "default" in personas
    assert "coding-agent" in personas


def test_get_all_personas_empty(config):
    """Test getting personas when none configured."""
    personas = config.get_all_personas()
    assert personas == []


def test_is_sync_enabled(config):
    """Test is_sync_enabled combines all checks."""
    # Not configured, should be False
    assert config.is_sync_enabled("default") is False

    # Configured but globally disabled
    config.setup("https://test.com", "token", enable=False)
    assert config.is_sync_enabled("default") is False

    # Configured and globally enabled, persona default enabled
    config.set_global_enabled(True)
    assert config.is_sync_enabled("default") is True

    # Configured and globally enabled, but persona disabled
    config.set_persona_enabled("default", False)
    assert config.is_sync_enabled("default") is False


def test_validate_success(config):
    """Test validation passes with valid config."""
    config.setup("https://memory-proxy.example.com", "test-token")

    is_valid, errors = config.validate()

    assert is_valid is True
    assert len(errors) == 0


def test_validate_missing_url(config):
    """Test validation fails with missing URL."""
    config.setup("", "test-token")

    is_valid, errors = config.validate()

    assert is_valid is False
    assert any("Remote URL" in err for err in errors)


def test_validate_missing_token(config):
    """Test validation fails with missing token."""
    config.setup("https://test.com", "")

    is_valid, errors = config.validate()

    assert is_valid is False
    assert any("token" in err for err in errors)


def test_validate_invalid_url_scheme(config):
    """Test validation fails with invalid URL scheme."""
    config.setup("ftp://test.com", "token")

    is_valid, errors = config.validate()

    assert is_valid is False
    assert any("http://" in err or "https://" in err for err in errors)


def test_validate_multiple_errors(config):
    """Test validation returns all errors."""
    # Leave everything unconfigured
    is_valid, errors = config.validate()

    assert is_valid is False
    assert len(errors) >= 2  # At least URL and token missing


def test_config_persists_between_instances(temp_config_dir):
    """Test that config persists between instances."""
    config_path = temp_config_dir / "memory_proxy.json"

    # First instance
    config1 = MemoryProxyConfig(config_path=config_path)
    config1.setup("https://test.com", "token")
    config1.set_persona_enabled("default", False)

    # Second instance should load persisted config
    config2 = MemoryProxyConfig(config_path=config_path)

    assert config2.remote_url == "https://test.com"
    assert config2.is_persona_enabled("default") is False


def test_config_creates_directory(temp_config_dir):
    """Test that config creates parent directory if needed."""
    nested_path = temp_config_dir / "nested" / "dir" / "config.json"
    config = MemoryProxyConfig(config_path=nested_path)

    config.setup("https://test.com", "token")

    assert nested_path.exists()
    assert nested_path.parent.exists()


def test_config_repr(config):
    """Test string representation of config."""
    config.setup("https://test.com", "token", enable=True)
    config.set_persona_enabled("default", True)

    repr_str = repr(config)

    assert "https://test.com" in repr_str
    assert "enabled=True" in repr_str
    assert "configured=True" in repr_str
    # Token should NOT be in repr
    assert "token" not in repr_str


def test_invalid_json_falls_back_to_default(temp_config_dir):
    """Test that invalid JSON falls back to default config."""
    config_path = temp_config_dir / "memory_proxy.json"

    # Write invalid JSON
    with open(config_path, "w") as f:
        f.write("{ invalid json }")

    config = MemoryProxyConfig(config_path=config_path)

    # Should fall back to defaults
    assert config.is_configured is False
    assert config.is_globally_enabled is False


def test_corrupted_last_sync_returns_none(config):
    """Test that corrupted last_sync timestamp returns None."""
    config.setup("https://test.com", "token")

    # Manually corrupt the timestamp
    config._config["personas"] = {
        "default": {
            "last_sync": "not-a-valid-timestamp",
        }
    }

    last_sync = config.get_last_sync("default")
    assert last_sync is None
