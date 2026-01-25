"""Tests for MCP server authorization flow support."""

from datetime import datetime, timedelta, timezone

import pytest

from silica.developer.mcp.auth import (
    APIKeyFlowHandler,
    AuthFlowCancelled,
    AuthRequiredError,
    MCPAuthHandler,
    OAuthFlowHandler,
    detect_auth_requirement_from_error,
)
from silica.developer.mcp.config import MCPAuthConfig, MCPServerConfig
from silica.developer.mcp.credentials import (
    APIKeyCredentials,
    FileBackend,
    MCPCredentialStore,
    OAuthCredentials,
)


class TestAuthRequiredError:
    """Tests for AuthRequiredError."""

    def test_attributes(self):
        """Test error has expected attributes."""
        error = AuthRequiredError("test-server", "oauth", "Custom message")

        assert error.server_name == "test-server"
        assert error.auth_type == "oauth"
        assert "Custom message" in str(error)

    def test_default_message(self):
        """Test default message generation."""
        error = AuthRequiredError("test-server", "api_key")

        assert "test-server" in str(error)
        assert "api_key" in str(error)


class TestAuthFlowCancelled:
    """Tests for AuthFlowCancelled."""

    def test_attributes(self):
        """Test error has expected attributes."""
        error = AuthFlowCancelled("test-server")

        assert error.server_name == "test-server"
        assert "test-server" in str(error)


class TestOAuthFlowHandler:
    """Tests for OAuthFlowHandler."""

    @pytest.mark.asyncio
    async def test_incomplete_config(self):
        """Test raises error for incomplete OAuth config."""
        handler = OAuthFlowHandler(
            open_browser=False,
            prompt_callback=lambda x: "code",
        )

        config = MCPAuthConfig(type="oauth")  # Missing required fields

        with pytest.raises(AuthRequiredError) as exc_info:
            await handler.run(config, "test-server")

        assert "incomplete" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_no_prompt_callback(self):
        """Test raises error without prompt callback."""
        handler = OAuthFlowHandler(
            open_browser=False,
            prompt_callback=None,
        )

        config = MCPAuthConfig(
            type="oauth",
            client_id="test-client",
            extra={
                "auth_url": "https://auth.example.com/authorize",
                "token_url": "https://auth.example.com/token",
            },
        )

        with pytest.raises(AuthRequiredError):
            await handler.run(config, "test-server")

    @pytest.mark.asyncio
    async def test_cancelled_when_empty_code(self):
        """Test raises cancelled when user enters empty code."""
        handler = OAuthFlowHandler(
            open_browser=False,
            prompt_callback=lambda x: "",  # Empty code
        )

        config = MCPAuthConfig(
            type="oauth",
            client_id="test-client",
            extra={
                "auth_url": "https://auth.example.com/authorize",
                "token_url": "https://auth.example.com/token",
            },
        )

        with pytest.raises(AuthFlowCancelled):
            await handler.run(config, "test-server")

    @pytest.mark.asyncio
    async def test_returns_credentials_with_code(self):
        """Test returns credentials when code provided."""
        handler = OAuthFlowHandler(
            open_browser=False,
            prompt_callback=lambda x: "auth-code-123",
        )

        config = MCPAuthConfig(
            type="oauth",
            client_id="test-client",
            scopes=["read", "write"],
            extra={
                "auth_url": "https://auth.example.com/authorize",
                "token_url": "https://auth.example.com/token",
            },
        )

        result = await handler.run(config, "test-server")

        assert isinstance(result, OAuthCredentials)
        assert result.scopes == ["read", "write"]


class TestAPIKeyFlowHandler:
    """Tests for APIKeyFlowHandler."""

    @pytest.mark.asyncio
    async def test_no_prompt_callback(self):
        """Test raises error without prompt callback."""
        handler = APIKeyFlowHandler(prompt_callback=None)

        config = MCPAuthConfig(type="api_key")

        with pytest.raises(AuthRequiredError):
            await handler.run(config, "test-server")

    @pytest.mark.asyncio
    async def test_cancelled_when_empty_key(self):
        """Test raises cancelled when user enters empty key."""
        handler = APIKeyFlowHandler(prompt_callback=lambda x: "")

        config = MCPAuthConfig(type="api_key")

        with pytest.raises(AuthFlowCancelled):
            await handler.run(config, "test-server")

    @pytest.mark.asyncio
    async def test_returns_credentials(self):
        """Test returns credentials when key provided."""
        handler = APIKeyFlowHandler(prompt_callback=lambda x: "secret-key-123")

        config = MCPAuthConfig(type="api_key")

        result = await handler.run(config, "test-server")

        assert isinstance(result, APIKeyCredentials)
        assert result.api_key == "secret-key-123"


class TestMCPAuthHandler:
    """Tests for MCPAuthHandler."""

    def create_handler(self, tmp_path, prompt_callback=None):
        """Create auth handler with file backend."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))
        return MCPAuthHandler(
            credential_store=store,
            open_browser=False,
            prompt_callback=prompt_callback,
        )

    def test_needs_auth_no_config(self, tmp_path):
        """Test needs_auth returns False when no auth config."""
        handler = self.create_handler(tmp_path)

        config = MCPServerConfig(name="test", command="cmd", args=[])

        assert handler.needs_auth(config) is False

    def test_needs_auth_no_credentials(self, tmp_path):
        """Test needs_auth returns True when no credentials stored."""
        handler = self.create_handler(tmp_path)

        config = MCPServerConfig(
            name="test",
            command="cmd",
            args=[],
            auth=MCPAuthConfig(type="api_key"),
        )

        assert handler.needs_auth(config) is True

    def test_needs_auth_with_valid_credentials(self, tmp_path):
        """Test needs_auth returns False with valid credentials."""
        handler = self.create_handler(tmp_path)
        handler.credential_store.store_credentials(
            "test", APIKeyCredentials(api_key="key")
        )

        config = MCPServerConfig(
            name="test",
            command="cmd",
            args=[],
            auth=MCPAuthConfig(type="api_key"),
        )

        assert handler.needs_auth(config) is False

    def test_needs_auth_with_expired_credentials(self, tmp_path):
        """Test needs_auth returns True with expired credentials."""
        handler = self.create_handler(tmp_path)
        handler.credential_store.store_credentials(
            "test",
            OAuthCredentials(
                access_token="token",
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
        )

        config = MCPServerConfig(
            name="test",
            command="cmd",
            args=[],
            auth=MCPAuthConfig(type="oauth"),
        )

        assert handler.needs_auth(config) is True

    def test_get_auth_type(self, tmp_path):
        """Test get_auth_type returns correct type."""
        handler = self.create_handler(tmp_path)

        # No auth
        config1 = MCPServerConfig(name="test", command="cmd", args=[])
        assert handler.get_auth_type(config1) is None

        # With auth
        config2 = MCPServerConfig(
            name="test",
            command="cmd",
            args=[],
            auth=MCPAuthConfig(type="oauth"),
        )
        assert handler.get_auth_type(config2) == "oauth"

    def test_get_credentials(self, tmp_path):
        """Test get_credentials retrieves stored credentials."""
        handler = self.create_handler(tmp_path)
        handler.credential_store.store_credentials(
            "test", APIKeyCredentials(api_key="secret")
        )

        config = MCPServerConfig(name="test", command="cmd", args=[])
        creds = handler.get_credentials(config)

        assert isinstance(creds, APIKeyCredentials)
        assert creds.api_key == "secret"

    def test_get_auth_status_not_required(self, tmp_path):
        """Test auth status when no auth config."""
        handler = self.create_handler(tmp_path)
        config = MCPServerConfig(name="test", command="cmd", args=[])

        assert handler.get_auth_status(config) == "not_required"

    def test_get_auth_status_not_configured(self, tmp_path):
        """Test auth status when no credentials."""
        handler = self.create_handler(tmp_path)
        config = MCPServerConfig(
            name="test",
            command="cmd",
            args=[],
            auth=MCPAuthConfig(type="api_key"),
        )

        assert handler.get_auth_status(config) == "not_configured"

    def test_get_auth_status_authenticated(self, tmp_path):
        """Test auth status with valid credentials."""
        handler = self.create_handler(tmp_path)
        handler.credential_store.store_credentials(
            "test", APIKeyCredentials(api_key="key")
        )

        config = MCPServerConfig(
            name="test",
            command="cmd",
            args=[],
            auth=MCPAuthConfig(type="api_key"),
        )

        assert handler.get_auth_status(config) == "authenticated"

    @pytest.mark.asyncio
    async def test_authenticate_no_auth_config(self, tmp_path):
        """Test authenticate raises error without auth config."""
        handler = self.create_handler(tmp_path)
        config = MCPServerConfig(name="test", command="cmd", args=[])

        with pytest.raises(AuthRequiredError):
            await handler.authenticate(config)

    @pytest.mark.asyncio
    async def test_authenticate_unsupported_type(self, tmp_path):
        """Test authenticate raises error for unsupported type."""
        handler = self.create_handler(tmp_path, prompt_callback=lambda x: "value")
        config = MCPServerConfig(
            name="test",
            command="cmd",
            args=[],
            auth=MCPAuthConfig(type="unsupported"),
        )

        with pytest.raises(AuthRequiredError) as exc_info:
            await handler.authenticate(config)

        assert "unsupported" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_authenticate_api_key(self, tmp_path):
        """Test authenticate with API key flow."""
        handler = self.create_handler(tmp_path, prompt_callback=lambda x: "my-api-key")

        config = MCPServerConfig(
            name="test",
            command="cmd",
            args=[],
            auth=MCPAuthConfig(type="api_key"),
        )

        result = await handler.authenticate(config)

        assert isinstance(result, APIKeyCredentials)
        assert result.api_key == "my-api-key"

        # Verify stored
        stored = handler.credential_store.get_credentials("test")
        assert stored.api_key == "my-api-key"

    def test_revoke_credentials(self, tmp_path):
        """Test revoke_credentials removes stored credentials."""
        handler = self.create_handler(tmp_path)
        handler.credential_store.store_credentials(
            "test", APIKeyCredentials(api_key="key")
        )

        config = MCPServerConfig(name="test", command="cmd", args=[])
        handler.revoke_credentials(config)

        assert handler.credential_store.get_credentials("test") is None


class TestDetectAuthRequirement:
    """Tests for detect_auth_requirement_from_error."""

    def test_detects_unauthorized(self):
        """Test detects unauthorized errors."""
        error = Exception("401 Unauthorized")
        assert detect_auth_requirement_from_error(error) == "api_key"

    def test_detects_invalid_api_key(self):
        """Test detects invalid API key errors."""
        error = Exception("Invalid API Key provided")
        assert detect_auth_requirement_from_error(error) == "api_key"

    def test_detects_oauth_errors(self):
        """Test detects OAuth-related errors."""
        error = Exception("OAuth token expired")
        assert detect_auth_requirement_from_error(error) == "oauth"

    def test_detects_access_token_errors(self):
        """Test detects access token errors."""
        error = Exception("Access token invalid")
        assert detect_auth_requirement_from_error(error) == "oauth"

    def test_returns_none_for_unrelated_errors(self):
        """Test returns None for non-auth errors."""
        error = Exception("Connection refused")
        assert detect_auth_requirement_from_error(error) is None

    def test_case_insensitive(self):
        """Test detection is case insensitive."""
        error = Exception("UNAUTHORIZED ACCESS")
        assert detect_auth_requirement_from_error(error) == "api_key"
