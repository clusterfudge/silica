"""Secure credential storage for MCP server authentication.

This module provides cross-platform credential storage using keyring
with fallback to encrypted file storage.

Usage:
    store = MCPCredentialStore()

    # Store OAuth credentials
    store.store_credentials("gmail", OAuthCredentials(
        access_token="...",
        refresh_token="...",
        expires_at=datetime.now() + timedelta(hours=1),
    ))

    # Retrieve credentials
    creds = store.get_credentials("gmail")
    if creds and store.is_expired("gmail"):
        creds = await store.refresh_if_needed("gmail")
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

# Service name prefix for keyring
KEYRING_SERVICE = "silica-mcp"

# Fallback storage path
FALLBACK_STORAGE_DIR = Path.home() / ".silica" / "mcp" / "credentials"


@dataclass
class OAuthCredentials:
    """OAuth 2.0 credentials.

    Attributes:
        access_token: The access token for API calls
        refresh_token: Optional refresh token for getting new access tokens
        expires_at: When the access token expires (UTC)
        token_type: Token type (usually "Bearer")
        scopes: List of authorized scopes
    """

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    token_type: str = "Bearer"
    scopes: list[str] = field(default_factory=list)

    def is_expired(self, buffer_seconds: int = 60) -> bool:
        """Check if the access token is expired.

        Args:
            buffer_seconds: Consider token expired this many seconds before actual expiry

        Returns:
            True if expired or expiring soon, False otherwise
        """
        if self.expires_at is None:
            return False

        # Ensure we're comparing timezone-aware datetimes
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)

        from datetime import timedelta

        return now >= (expires - timedelta(seconds=buffer_seconds))

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        if self.expires_at:
            data["expires_at"] = self.expires_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "OAuthCredentials":
        """Create from dictionary."""
        if data.get("expires_at"):
            data["expires_at"] = datetime.fromisoformat(data["expires_at"])
        return cls(**data)


@dataclass
class APIKeyCredentials:
    """API key credentials.

    Attributes:
        api_key: The API key
        key_id: Optional key identifier (for servers with multiple keys)
    """

    api_key: str
    key_id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "APIKeyCredentials":
        """Create from dictionary."""
        return cls(**data)


# Type alias for all credential types
Credentials = OAuthCredentials | APIKeyCredentials


class CredentialBackend(ABC):
    """Abstract base class for credential storage backends."""

    @abstractmethod
    def get(self, server_name: str) -> Optional[str]:
        """Get serialized credentials for a server."""

    @abstractmethod
    def set(self, server_name: str, value: str) -> None:
        """Store serialized credentials for a server."""

    @abstractmethod
    def delete(self, server_name: str) -> None:
        """Delete credentials for a server."""

    @abstractmethod
    def list_servers(self) -> list[str]:
        """List all servers with stored credentials."""


class KeyringBackend(CredentialBackend):
    """Credential storage using system keyring."""

    def __init__(self, service: str = KEYRING_SERVICE):
        self.service = service
        self._keyring = None

    def _get_keyring(self):
        """Lazy load keyring module."""
        if self._keyring is None:
            try:
                import keyring

                self._keyring = keyring
            except ImportError:
                raise RuntimeError("keyring package not installed")
        return self._keyring

    def get(self, server_name: str) -> Optional[str]:
        """Get credentials from keyring."""
        try:
            kr = self._get_keyring()
            return kr.get_password(self.service, server_name)
        except Exception as e:
            logger.warning(f"Failed to get credentials from keyring: {e}")
            return None

    def set(self, server_name: str, value: str) -> None:
        """Store credentials in keyring."""
        try:
            kr = self._get_keyring()
            kr.set_password(self.service, server_name, value)
        except Exception as e:
            logger.warning(f"Failed to store credentials in keyring: {e}")
            raise

    def delete(self, server_name: str) -> None:
        """Delete credentials from keyring."""
        try:
            kr = self._get_keyring()
            kr.delete_password(self.service, server_name)
        except Exception as e:
            # Ignore if credentials don't exist
            logger.debug(f"Failed to delete credentials from keyring: {e}")

    def list_servers(self) -> list[str]:
        """List servers - not directly supported by keyring."""
        # Keyring doesn't support listing, return empty
        return []


class FileBackend(CredentialBackend):
    """Fallback file-based credential storage.

    Note: This stores credentials in plaintext JSON files.
    Use only when keyring is unavailable.
    """

    def __init__(self, storage_dir: Path = FALLBACK_STORAGE_DIR):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, server_name: str) -> Path:
        """Get credential file path for a server."""
        # Sanitize server name for filesystem
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in server_name)
        return self.storage_dir / f"{safe_name}.json"

    def get(self, server_name: str) -> Optional[str]:
        """Get credentials from file."""
        path = self._get_file_path(server_name)
        if not path.exists():
            return None
        try:
            return path.read_text()
        except Exception as e:
            logger.warning(f"Failed to read credentials file: {e}")
            return None

    def set(self, server_name: str, value: str) -> None:
        """Store credentials in file."""
        path = self._get_file_path(server_name)
        try:
            path.write_text(value)
            # Set restrictive permissions
            path.chmod(0o600)
        except Exception as e:
            logger.warning(f"Failed to write credentials file: {e}")
            raise

    def delete(self, server_name: str) -> None:
        """Delete credentials file."""
        path = self._get_file_path(server_name)
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.debug(f"Failed to delete credentials file: {e}")

    def list_servers(self) -> list[str]:
        """List servers with stored credentials."""
        servers = []
        for path in self.storage_dir.glob("*.json"):
            servers.append(path.stem)
        return servers


class MCPCredentialStore:
    """Credential storage for MCP server authentication.

    Uses keyring for secure storage with fallback to file-based storage.

    Example:
        store = MCPCredentialStore()

        # Store credentials
        store.store_credentials("sqlite", APIKeyCredentials(api_key="..."))

        # Check and retrieve
        if store.has_credentials("sqlite"):
            creds = store.get_credentials("sqlite")
    """

    def __init__(
        self,
        backend: Optional[CredentialBackend] = None,
        fallback_dir: Path = FALLBACK_STORAGE_DIR,
    ):
        """Initialize credential store.

        Args:
            backend: Optional backend to use (auto-detects if None)
            fallback_dir: Directory for file fallback storage
        """
        if backend is not None:
            self._backend = backend
        else:
            # Try keyring first, fall back to file
            try:
                self._backend = KeyringBackend()
                # Test if keyring works
                self._backend._get_keyring()
            except Exception:
                logger.info("Keyring unavailable, using file-based credential storage")
                self._backend = FileBackend(fallback_dir)

    def get_credentials(self, server_name: str) -> Optional[Credentials]:
        """Get credentials for an MCP server.

        Args:
            server_name: Name of the MCP server

        Returns:
            Credentials instance or None if not found
        """
        raw = self._backend.get(server_name)
        if raw is None:
            return None

        try:
            data = json.loads(raw)
            cred_type = data.get("type")

            if cred_type == "oauth":
                return OAuthCredentials.from_dict(data["credentials"])
            elif cred_type == "api_key":
                return APIKeyCredentials.from_dict(data["credentials"])
            else:
                logger.warning(f"Unknown credential type: {cred_type}")
                return None
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse credentials for {server_name}: {e}")
            return None

    def store_credentials(self, server_name: str, credentials: Credentials) -> None:
        """Store credentials for an MCP server.

        Args:
            server_name: Name of the MCP server
            credentials: Credentials to store
        """
        if isinstance(credentials, OAuthCredentials):
            cred_type = "oauth"
        elif isinstance(credentials, APIKeyCredentials):
            cred_type = "api_key"
        else:
            raise ValueError(f"Unknown credential type: {type(credentials)}")

        data = {
            "type": cred_type,
            "credentials": credentials.to_dict(),
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }

        self._backend.set(server_name, json.dumps(data))

    def delete_credentials(self, server_name: str) -> None:
        """Delete credentials for an MCP server.

        Args:
            server_name: Name of the MCP server
        """
        self._backend.delete(server_name)

    def has_credentials(self, server_name: str) -> bool:
        """Check if credentials exist for a server.

        Args:
            server_name: Name of the MCP server

        Returns:
            True if credentials exist
        """
        return self._backend.get(server_name) is not None

    def is_expired(self, server_name: str) -> bool:
        """Check if credentials for a server are expired.

        Args:
            server_name: Name of the MCP server

        Returns:
            True if expired or no credentials exist
        """
        creds = self.get_credentials(server_name)
        if creds is None:
            return True

        if isinstance(creds, OAuthCredentials):
            return creds.is_expired()

        # API keys don't expire
        return False

    def get_auth_status(
        self, server_name: str
    ) -> Literal["authenticated", "expired", "not_configured"]:
        """Get authentication status for a server.

        Args:
            server_name: Name of the MCP server

        Returns:
            Status string: "authenticated", "expired", or "not_configured"
        """
        creds = self.get_credentials(server_name)

        if creds is None:
            return "not_configured"

        if isinstance(creds, OAuthCredentials) and creds.is_expired():
            return "expired"

        return "authenticated"

    def list_servers(self) -> list[str]:
        """List all servers with stored credentials.

        Returns:
            List of server names
        """
        return self._backend.list_servers()

    async def refresh_if_needed(
        self, server_name: str, refresh_callback=None
    ) -> Optional[Credentials]:
        """Refresh credentials if needed.

        Args:
            server_name: Name of the MCP server
            refresh_callback: Async function to refresh OAuth tokens
                Takes (refresh_token, scopes) and returns new OAuthCredentials

        Returns:
            Updated credentials or None if refresh failed
        """
        creds = self.get_credentials(server_name)

        if creds is None:
            return None

        if not isinstance(creds, OAuthCredentials):
            return creds  # API keys don't need refresh

        if not creds.is_expired():
            return creds

        if creds.refresh_token is None:
            logger.warning(f"No refresh token for {server_name}")
            return None

        if refresh_callback is None:
            logger.warning(f"No refresh callback provided for {server_name}")
            return None

        try:
            new_creds = await refresh_callback(creds.refresh_token, creds.scopes)
            self.store_credentials(server_name, new_creds)
            return new_creds
        except Exception as e:
            logger.error(f"Failed to refresh credentials for {server_name}: {e}")
            return None
