"""MCP server authorization flow support.

This module provides authorization flow handling for MCP servers that require
authentication (OAuth, API keys, etc.).

Usage:
    from silica.developer.mcp.auth import MCPAuthHandler, AuthRequiredError

    handler = MCPAuthHandler(credential_store)

    # Check if auth is needed
    if handler.needs_auth(server_config):
        # Run auth flow
        await handler.authenticate(server_config)

    # Or handle auth errors from connection
    try:
        await client.connect()
    except AuthRequiredError as e:
        await handler.authenticate(server_config)
"""

from __future__ import annotations

import logging
import webbrowser
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from silica.developer.mcp.config import MCPAuthConfig, MCPServerConfig
    from silica.developer.mcp.credentials import (
        Credentials,
        MCPCredentialStore,
    )

logger = logging.getLogger(__name__)


class AuthRequiredError(Exception):
    """Raised when authentication is required for an MCP server."""

    def __init__(self, server_name: str, auth_type: str, message: str = ""):
        self.server_name = server_name
        self.auth_type = auth_type
        super().__init__(
            message or f"Authentication required for {server_name} ({auth_type})"
        )


class AuthFlowCancelled(Exception):
    """Raised when user cancels an auth flow."""

    def __init__(self, server_name: str):
        self.server_name = server_name
        super().__init__(f"Authentication cancelled for {server_name}")


@dataclass
class OAuthFlowResult:
    """Result from an OAuth authorization flow.

    Attributes:
        access_token: The access token
        refresh_token: Optional refresh token
        expires_in: Token lifetime in seconds (optional)
        token_type: Token type (usually "Bearer")
        scope: Space-separated authorized scopes
    """

    access_token: str
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None
    token_type: str = "Bearer"
    scope: str = ""


class AuthFlowHandler(ABC):
    """Abstract base class for auth flow handlers."""

    @abstractmethod
    async def run(self, config: "MCPAuthConfig", server_name: str) -> "Credentials":
        """Run the authorization flow.

        Args:
            config: Auth configuration from server config
            server_name: Name of the MCP server

        Returns:
            Credentials obtained from the auth flow

        Raises:
            AuthFlowCancelled: If user cancels the flow
            AuthRequiredError: If auth flow fails
        """


class OAuthFlowHandler(AuthFlowHandler):
    """Handler for OAuth 2.0 authorization flows.

    Supports:
    - Browser-based authorization code flow
    - Manual code entry for headless environments
    - Token refresh
    """

    def __init__(
        self,
        open_browser: bool = True,
        prompt_callback: Optional[Callable[[str], str]] = None,
    ):
        """Initialize OAuth handler.

        Args:
            open_browser: Whether to automatically open browser for auth
            prompt_callback: Optional callback for prompting user input
                Takes a prompt string, returns user input
        """
        self.open_browser = open_browser
        self.prompt_callback = prompt_callback

    async def run(self, config: "MCPAuthConfig", server_name: str) -> "Credentials":
        """Run OAuth authorization flow."""
        from datetime import datetime, timedelta, timezone

        from silica.developer.mcp.credentials import OAuthCredentials

        # For now, this is a placeholder that shows how the flow would work
        # Actual implementation would depend on the OAuth provider

        # Get OAuth configuration from config and extra dict
        auth_url = config.extra.get("auth_url")
        token_url = config.extra.get("token_url")
        client_id = config.client_id
        scopes = config.scopes or []

        if not auth_url or not token_url or not client_id:
            raise AuthRequiredError(
                server_name,
                "oauth",
                f"OAuth configuration incomplete for {server_name}",
            )

        # Build authorization URL
        redirect_uri = (
            config.extra.get("redirect_uri") or "http://localhost:8085/callback"
        )
        scope_str = " ".join(scopes)

        auth_request_url = (
            f"{auth_url}?"
            f"client_id={client_id}&"
            f"redirect_uri={redirect_uri}&"
            f"response_type=code&"
            f"scope={scope_str}"
        )

        # Open browser or display URL
        if self.open_browser:
            logger.info(f"Opening browser for {server_name} authorization...")
            webbrowser.open(auth_request_url)
        else:
            logger.info(f"Authorization URL: {auth_request_url}")

        # Get authorization code from user
        if self.prompt_callback:
            code = self.prompt_callback(f"Enter authorization code for {server_name}: ")
        else:
            raise AuthRequiredError(
                server_name,
                "oauth",
                "No prompt callback available for authorization code entry",
            )

        if not code:
            raise AuthFlowCancelled(server_name)

        # Exchange code for tokens
        # This is a placeholder - actual implementation would make HTTP request
        # to token_url with the authorization code

        # For now, return placeholder credentials
        # Real implementation would parse token response
        return OAuthCredentials(
            access_token="placeholder_token",
            refresh_token="placeholder_refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=scopes,
        )


class APIKeyFlowHandler(AuthFlowHandler):
    """Handler for API key authentication."""

    def __init__(self, prompt_callback: Optional[Callable[[str], str]] = None):
        """Initialize API key handler.

        Args:
            prompt_callback: Callback for prompting user input
        """
        self.prompt_callback = prompt_callback

    async def run(self, config: "MCPAuthConfig", server_name: str) -> "Credentials":
        """Prompt for API key."""
        from silica.developer.mcp.credentials import APIKeyCredentials

        if not self.prompt_callback:
            raise AuthRequiredError(
                server_name,
                "api_key",
                "No prompt callback available for API key entry",
            )

        api_key = self.prompt_callback(f"Enter API key for {server_name}: ")

        if not api_key:
            raise AuthFlowCancelled(server_name)

        return APIKeyCredentials(api_key=api_key)


class MCPAuthHandler:
    """Handles authentication for MCP servers.

    Coordinates between auth configuration, credential storage, and auth flows.

    Example:
        store = MCPCredentialStore()
        handler = MCPAuthHandler(store)

        # Check if auth needed
        if handler.needs_auth(server_config):
            await handler.authenticate(server_config)

        # Get credentials for a connection
        creds = handler.get_credentials(server_config)
    """

    def __init__(
        self,
        credential_store: "MCPCredentialStore",
        open_browser: bool = True,
        prompt_callback: Optional[Callable[[str], str]] = None,
    ):
        """Initialize auth handler.

        Args:
            credential_store: Credential storage instance
            open_browser: Whether to open browser for OAuth flows
            prompt_callback: Callback for prompting user input
        """
        self.credential_store = credential_store
        self.open_browser = open_browser
        self.prompt_callback = prompt_callback

        # Initialize flow handlers
        self._oauth_handler = OAuthFlowHandler(
            open_browser=open_browser,
            prompt_callback=prompt_callback,
        )
        self._api_key_handler = APIKeyFlowHandler(prompt_callback=prompt_callback)

    def needs_auth(self, server_config: "MCPServerConfig") -> bool:
        """Check if authentication is needed for a server.

        Args:
            server_config: Server configuration

        Returns:
            True if auth is required and not configured
        """
        auth_config = server_config.auth
        if auth_config is None:
            return False

        # Check if we have valid credentials
        server_name = server_config.name
        if not self.credential_store.has_credentials(server_name):
            return True

        # Check if credentials are expired
        if self.credential_store.is_expired(server_name):
            return True

        return False

    def get_auth_type(self, server_config: "MCPServerConfig") -> Optional[str]:
        """Get the authentication type for a server.

        Args:
            server_config: Server configuration

        Returns:
            Auth type string or None if no auth required
        """
        if server_config.auth is None:
            return None
        return server_config.auth.type

    def get_credentials(
        self, server_config: "MCPServerConfig"
    ) -> Optional["Credentials"]:
        """Get stored credentials for a server.

        Args:
            server_config: Server configuration

        Returns:
            Stored credentials or None
        """
        return self.credential_store.get_credentials(server_config.name)

    def get_auth_status(self, server_config: "MCPServerConfig") -> str:
        """Get authentication status for a server.

        Args:
            server_config: Server configuration

        Returns:
            Status string: "authenticated", "expired", "not_configured", or "not_required"
        """
        if server_config.auth is None:
            return "not_required"

        return self.credential_store.get_auth_status(server_config.name)

    async def authenticate(self, server_config: "MCPServerConfig") -> "Credentials":
        """Run authentication flow for a server.

        Args:
            server_config: Server configuration

        Returns:
            Obtained credentials

        Raises:
            AuthRequiredError: If auth config is missing or invalid
            AuthFlowCancelled: If user cancels the flow
        """
        auth_config = server_config.auth
        if auth_config is None:
            raise AuthRequiredError(
                server_config.name,
                "unknown",
                f"No auth configuration for {server_config.name}",
            )

        server_name = server_config.name
        auth_type = auth_config.type

        # Select handler based on auth type
        if auth_type == "oauth":
            handler = self._oauth_handler
        elif auth_type == "api_key":
            handler = self._api_key_handler
        else:
            raise AuthRequiredError(
                server_name,
                auth_type,
                f"Unsupported auth type: {auth_type}",
            )

        # Run the auth flow
        credentials = await handler.run(auth_config, server_name)

        # Store credentials
        self.credential_store.store_credentials(server_name, credentials)

        logger.info(f"Successfully authenticated {server_name}")
        return credentials

    async def refresh_credentials(
        self, server_config: "MCPServerConfig"
    ) -> Optional["Credentials"]:
        """Refresh credentials for a server if needed.

        Args:
            server_config: Server configuration

        Returns:
            Refreshed credentials or None if refresh not possible
        """
        server_name = server_config.name

        async def refresh_callback(refresh_token: str, scopes: list[str]):
            # Placeholder for actual token refresh
            # Real implementation would make HTTP request to token endpoint
            from datetime import datetime, timedelta, timezone

            from silica.developer.mcp.credentials import OAuthCredentials

            return OAuthCredentials(
                access_token="refreshed_token",
                refresh_token=refresh_token,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                scopes=scopes,
            )

        return await self.credential_store.refresh_if_needed(
            server_name, refresh_callback
        )

    def revoke_credentials(self, server_config: "MCPServerConfig") -> None:
        """Revoke stored credentials for a server.

        Args:
            server_config: Server configuration
        """
        self.credential_store.delete_credentials(server_config.name)
        logger.info(f"Revoked credentials for {server_config.name}")


def detect_auth_requirement_from_error(error: Exception) -> Optional[str]:
    """Detect if an error indicates authentication is required.

    Args:
        error: Exception from MCP connection or tool call

    Returns:
        Auth type string if auth required, None otherwise
    """
    error_str = str(error).lower()

    # Common auth-related error patterns
    auth_patterns = [
        ("unauthorized", "api_key"),
        ("401", "api_key"),
        ("authentication required", "api_key"),
        ("invalid api key", "api_key"),
        ("oauth", "oauth"),
        ("access token", "oauth"),
        ("token expired", "oauth"),
        ("login required", "oauth"),
    ]

    for pattern, auth_type in auth_patterns:
        if pattern in error_str:
            return auth_type

    return None
