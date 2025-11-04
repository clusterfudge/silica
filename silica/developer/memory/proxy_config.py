"""Configuration management for Memory Proxy client.

This module handles reading and writing the memory proxy configuration file,
which stores the remote URL, authentication token, and per-persona sync settings.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MemoryProxyConfig:
    """Memory proxy configuration manager.

    Manages configuration stored in ~/.silica/memory_proxy.json including:
    - Remote URL
    - Authentication token
    - Global enable/disable
    - Per-persona sync settings
    - Last sync timestamps
    """

    DEFAULT_CONFIG_PATH = Path.home() / ".silica" / "memory_proxy.json"

    def __init__(self, config_path: Path | None = None):
        """Initialize the configuration manager.

        Args:
            config_path: Path to config file (default: ~/.silica/memory_proxy.json)
        """
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self._config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """Load configuration from disk.

        Returns:
            Configuration dictionary, or default config if file doesn't exist
        """
        if not self.config_path.exists():
            logger.debug(f"Config file not found at {self.config_path}, using defaults")
            return self._default_config()

        try:
            with open(self.config_path, "r") as f:
                config = json.load(f)
                logger.debug(f"Loaded config from {self.config_path}")
                return config
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load config from {self.config_path}: {e}")
            return self._default_config()

    def _default_config(self) -> dict[str, Any]:
        """Get default configuration.

        Returns:
            Default configuration dictionary
        """
        return {
            "enabled": False,
            "remote_url": "",
            "auth_token": "",
            "personas": {},
            "version": 1,
        }

    def _save_config(self) -> None:
        """Save configuration to disk."""
        # Ensure directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(self.config_path, "w") as f:
                json.dump(self._config, f, indent=2)
                logger.debug(f"Saved config to {self.config_path}")
        except OSError as e:
            logger.error(f"Failed to save config to {self.config_path}: {e}")
            raise

    @property
    def is_configured(self) -> bool:
        """Check if memory proxy is configured.

        Returns:
            True if remote_url and auth_token are set
        """
        return bool(self._config.get("remote_url") and self._config.get("auth_token"))

    @property
    def is_globally_enabled(self) -> bool:
        """Check if memory proxy is globally enabled.

        Returns:
            True if globally enabled
        """
        return self._config.get("enabled", False)

    @property
    def remote_url(self) -> str:
        """Get the remote URL.

        Returns:
            Remote URL or empty string if not configured
        """
        return self._config.get("remote_url", "")

    @property
    def auth_token(self) -> str:
        """Get the authentication token.

        Returns:
            Auth token or empty string if not configured
        """
        return self._config.get("auth_token", "")

    def setup(self, remote_url: str, auth_token: str, enable: bool = True) -> None:
        """Setup memory proxy configuration.

        Args:
            remote_url: Remote memory proxy URL
            auth_token: Authentication token
            enable: Whether to globally enable memory proxy (default: True)
        """
        self._config["remote_url"] = remote_url.rstrip("/")
        self._config["auth_token"] = auth_token
        self._config["enabled"] = enable
        self._save_config()

        logger.info(f"Memory proxy configured: {remote_url} (enabled={enable})")

    def set_global_enabled(self, enabled: bool) -> None:
        """Set global enabled state.

        Args:
            enabled: Whether memory proxy should be globally enabled
        """
        self._config["enabled"] = enabled
        self._save_config()

        logger.info(f"Memory proxy globally {'enabled' if enabled else 'disabled'}")

    def is_persona_enabled(self, persona_name: str) -> bool:
        """Check if sync is enabled for a specific persona.

        Args:
            persona_name: Name of the persona

        Returns:
            True if sync is enabled for this persona (or globally if not set)
        """
        if not self.is_globally_enabled:
            return False

        personas = self._config.get("personas", {})
        persona_config = personas.get(persona_name, {})

        # Default to enabled if not explicitly set
        return persona_config.get("sync_enabled", True)

    def set_persona_enabled(self, persona_name: str, enabled: bool) -> None:
        """Enable or disable sync for a specific persona.

        Args:
            persona_name: Name of the persona
            enabled: Whether sync should be enabled for this persona
        """
        if "personas" not in self._config:
            self._config["personas"] = {}

        if persona_name not in self._config["personas"]:
            self._config["personas"][persona_name] = {}

        self._config["personas"][persona_name]["sync_enabled"] = enabled
        self._save_config()

        logger.info(
            f"Sync {'enabled' if enabled else 'disabled'} for persona: {persona_name}"
        )

    def get_last_sync(self, persona_name: str) -> datetime | None:
        """Get the last sync timestamp for a persona.

        Args:
            persona_name: Name of the persona

        Returns:
            Last sync datetime or None if never synced
        """
        personas = self._config.get("personas", {})
        persona_config = personas.get(persona_name, {})
        last_sync_str = persona_config.get("last_sync")

        if last_sync_str:
            try:
                return datetime.fromisoformat(last_sync_str)
            except ValueError:
                logger.error(f"Invalid last_sync timestamp: {last_sync_str}")
                return None

        return None

    def set_last_sync(self, persona_name: str, timestamp: datetime | None = None):
        """Set the last sync timestamp for a persona.

        Args:
            persona_name: Name of the persona
            timestamp: Sync timestamp (default: current time)
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        if "personas" not in self._config:
            self._config["personas"] = {}

        if persona_name not in self._config["personas"]:
            self._config["personas"][persona_name] = {}

        self._config["personas"][persona_name]["last_sync"] = timestamp.isoformat()
        self._save_config()

        logger.debug(f"Updated last_sync for {persona_name}: {timestamp}")

    def get_persona_config(self, persona_name: str) -> dict[str, Any]:
        """Get all configuration for a persona.

        Args:
            persona_name: Name of the persona

        Returns:
            Dictionary with persona configuration
        """
        personas = self._config.get("personas", {})
        return personas.get(persona_name, {})

    def get_all_personas(self) -> list[str]:
        """Get list of all configured personas.

        Returns:
            List of persona names
        """
        return list(self._config.get("personas", {}).keys())

    def is_sync_enabled(self, persona_name: str) -> bool:
        """Check if sync should actually happen for a persona.

        This checks both global enabled state and persona-specific enabled state.

        Args:
            persona_name: Name of the persona

        Returns:
            True if sync should happen for this persona
        """
        return self.is_configured and self.is_persona_enabled(persona_name)

    def validate(self) -> tuple[bool, list[str]]:
        """Validate the configuration.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        if not self.remote_url:
            errors.append("Remote URL is not configured")

        if not self.auth_token:
            errors.append("Authentication token is not configured")

        if self.remote_url and not (
            self.remote_url.startswith("http://")
            or self.remote_url.startswith("https://")
        ):
            errors.append("Remote URL must start with http:// or https://")

        return (len(errors) == 0, errors)

    def __repr__(self) -> str:
        """String representation of config (without sensitive data)."""
        return (
            f"MemoryProxyConfig("
            f"remote_url={self.remote_url}, "
            f"enabled={self.is_globally_enabled}, "
            f"configured={self.is_configured}, "
            f"personas={len(self._config.get('personas', {}))})"
        )
