"""Tests for MCP credential storage."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from silica.developer.mcp.credentials import (
    APIKeyCredentials,
    FileBackend,
    KeyringBackend,
    MCPCredentialStore,
    OAuthCredentials,
)


class TestOAuthCredentials:
    """Tests for OAuthCredentials."""

    def test_not_expired_when_no_expiry(self):
        """Test credentials without expiry are never expired."""
        creds = OAuthCredentials(access_token="token")
        assert creds.is_expired() is False

    def test_not_expired_when_valid(self):
        """Test credentials within validity period."""
        creds = OAuthCredentials(
            access_token="token",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert creds.is_expired() is False

    def test_expired_when_past_expiry(self):
        """Test credentials past expiry."""
        creds = OAuthCredentials(
            access_token="token",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert creds.is_expired() is True

    def test_expired_within_buffer(self):
        """Test credentials expiring within buffer period."""
        creds = OAuthCredentials(
            access_token="token",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        # Default buffer is 60 seconds
        assert creds.is_expired() is True
        # With smaller buffer
        assert creds.is_expired(buffer_seconds=10) is False

    def test_to_dict_and_from_dict(self):
        """Test serialization round-trip."""
        original = OAuthCredentials(
            access_token="token",
            refresh_token="refresh",
            expires_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            token_type="Bearer",
            scopes=["read", "write"],
        )

        data = original.to_dict()
        restored = OAuthCredentials.from_dict(data)

        assert restored.access_token == original.access_token
        assert restored.refresh_token == original.refresh_token
        assert restored.expires_at == original.expires_at
        assert restored.scopes == original.scopes


class TestAPIKeyCredentials:
    """Tests for APIKeyCredentials."""

    def test_to_dict_and_from_dict(self):
        """Test serialization round-trip."""
        original = APIKeyCredentials(
            api_key="secret-key",
            key_id="key-123",
        )

        data = original.to_dict()
        restored = APIKeyCredentials.from_dict(data)

        assert restored.api_key == original.api_key
        assert restored.key_id == original.key_id


class TestFileBackend:
    """Tests for FileBackend."""

    def test_set_and_get(self, tmp_path):
        """Test storing and retrieving credentials."""
        backend = FileBackend(tmp_path)

        backend.set("test-server", '{"key": "value"}')
        result = backend.get("test-server")

        assert result == '{"key": "value"}'

    def test_get_nonexistent(self, tmp_path):
        """Test getting credentials that don't exist."""
        backend = FileBackend(tmp_path)

        result = backend.get("nonexistent")

        assert result is None

    def test_delete(self, tmp_path):
        """Test deleting credentials."""
        backend = FileBackend(tmp_path)
        backend.set("test-server", '{"key": "value"}')

        backend.delete("test-server")

        assert backend.get("test-server") is None

    def test_list_servers(self, tmp_path):
        """Test listing servers with credentials."""
        backend = FileBackend(tmp_path)
        backend.set("server-a", "{}")
        backend.set("server-b", "{}")

        servers = backend.list_servers()

        assert set(servers) == {"server-a", "server-b"}

    def test_sanitizes_filename(self, tmp_path):
        """Test filename sanitization."""
        backend = FileBackend(tmp_path)
        backend.set("server/with:special!chars", '{"test": true}')

        # Should create file with sanitized name
        assert (tmp_path / "server_with_special_chars.json").exists()


class TestKeyringBackend:
    """Tests for KeyringBackend."""

    def test_get_calls_keyring(self):
        """Test get calls keyring.get_password."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = '{"test": true}'

        backend = KeyringBackend()
        backend._keyring = mock_keyring

        result = backend.get("test-server")

        mock_keyring.get_password.assert_called_once_with("silica-mcp", "test-server")
        assert result == '{"test": true}'

    def test_set_calls_keyring(self):
        """Test set calls keyring.set_password."""
        mock_keyring = MagicMock()

        backend = KeyringBackend()
        backend._keyring = mock_keyring

        backend.set("test-server", '{"test": true}')

        mock_keyring.set_password.assert_called_once_with(
            "silica-mcp", "test-server", '{"test": true}'
        )

    def test_delete_calls_keyring(self):
        """Test delete calls keyring.delete_password."""
        mock_keyring = MagicMock()

        backend = KeyringBackend()
        backend._keyring = mock_keyring

        backend.delete("test-server")

        mock_keyring.delete_password.assert_called_once_with(
            "silica-mcp", "test-server"
        )


class TestMCPCredentialStore:
    """Tests for MCPCredentialStore."""

    def test_store_and_get_oauth_credentials(self, tmp_path):
        """Test storing and retrieving OAuth credentials."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))

        creds = OAuthCredentials(
            access_token="access",
            refresh_token="refresh",
            expires_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            scopes=["read"],
        )

        store.store_credentials("gmail", creds)
        retrieved = store.get_credentials("gmail")

        assert isinstance(retrieved, OAuthCredentials)
        assert retrieved.access_token == "access"
        assert retrieved.refresh_token == "refresh"

    def test_store_and_get_api_key_credentials(self, tmp_path):
        """Test storing and retrieving API key credentials."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))

        creds = APIKeyCredentials(api_key="secret", key_id="123")

        store.store_credentials("github", creds)
        retrieved = store.get_credentials("github")

        assert isinstance(retrieved, APIKeyCredentials)
        assert retrieved.api_key == "secret"
        assert retrieved.key_id == "123"

    def test_get_nonexistent_credentials(self, tmp_path):
        """Test getting credentials that don't exist."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))

        result = store.get_credentials("nonexistent")

        assert result is None

    def test_delete_credentials(self, tmp_path):
        """Test deleting credentials."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))
        store.store_credentials("test", APIKeyCredentials(api_key="key"))

        store.delete_credentials("test")

        assert store.get_credentials("test") is None

    def test_has_credentials(self, tmp_path):
        """Test checking if credentials exist."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))

        assert store.has_credentials("test") is False

        store.store_credentials("test", APIKeyCredentials(api_key="key"))

        assert store.has_credentials("test") is True

    def test_is_expired_no_credentials(self, tmp_path):
        """Test is_expired returns True for missing credentials."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))

        assert store.is_expired("nonexistent") is True

    def test_is_expired_api_key_never_expires(self, tmp_path):
        """Test API keys never report as expired."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))
        store.store_credentials("test", APIKeyCredentials(api_key="key"))

        assert store.is_expired("test") is False

    def test_is_expired_oauth_valid(self, tmp_path):
        """Test OAuth with valid expiry."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))
        store.store_credentials(
            "test",
            OAuthCredentials(
                access_token="token",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
        )

        assert store.is_expired("test") is False

    def test_is_expired_oauth_expired(self, tmp_path):
        """Test OAuth past expiry."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))
        store.store_credentials(
            "test",
            OAuthCredentials(
                access_token="token",
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
        )

        assert store.is_expired("test") is True


class TestMCPCredentialStoreAuthStatus:
    """Tests for get_auth_status method."""

    def test_not_configured(self, tmp_path):
        """Test status when no credentials exist."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))

        assert store.get_auth_status("server") == "not_configured"

    def test_authenticated_api_key(self, tmp_path):
        """Test status with API key credentials."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))
        store.store_credentials("server", APIKeyCredentials(api_key="key"))

        assert store.get_auth_status("server") == "authenticated"

    def test_authenticated_oauth_valid(self, tmp_path):
        """Test status with valid OAuth credentials."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))
        store.store_credentials(
            "server",
            OAuthCredentials(
                access_token="token",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
        )

        assert store.get_auth_status("server") == "authenticated"

    def test_expired_oauth(self, tmp_path):
        """Test status with expired OAuth credentials."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))
        store.store_credentials(
            "server",
            OAuthCredentials(
                access_token="token",
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
        )

        assert store.get_auth_status("server") == "expired"


class TestMCPCredentialStoreRefresh:
    """Tests for refresh_if_needed method."""

    @pytest.mark.asyncio
    async def test_refresh_not_needed(self, tmp_path):
        """Test refresh when credentials are still valid."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))
        creds = OAuthCredentials(
            access_token="token",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        store.store_credentials("server", creds)

        callback = MagicMock()
        result = await store.refresh_if_needed("server", callback)

        callback.assert_not_called()
        assert result.access_token == "token"

    @pytest.mark.asyncio
    async def test_refresh_api_key(self, tmp_path):
        """Test refresh does nothing for API keys."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))
        store.store_credentials("server", APIKeyCredentials(api_key="key"))

        callback = MagicMock()
        result = await store.refresh_if_needed("server", callback)

        callback.assert_not_called()
        assert result.api_key == "key"

    @pytest.mark.asyncio
    async def test_refresh_no_refresh_token(self, tmp_path):
        """Test refresh fails without refresh token."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))
        store.store_credentials(
            "server",
            OAuthCredentials(
                access_token="token",
                refresh_token=None,
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
        )

        result = await store.refresh_if_needed("server", MagicMock())

        assert result is None

    @pytest.mark.asyncio
    async def test_refresh_success(self, tmp_path):
        """Test successful credential refresh."""
        store = MCPCredentialStore(backend=FileBackend(tmp_path))
        store.store_credentials(
            "server",
            OAuthCredentials(
                access_token="old-token",
                refresh_token="refresh-token",
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
                scopes=["read"],
            ),
        )

        new_creds = OAuthCredentials(
            access_token="new-token",
            refresh_token="new-refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        async def refresh_callback(refresh_token, scopes):
            assert refresh_token == "refresh-token"
            assert scopes == ["read"]
            return new_creds

        result = await store.refresh_if_needed("server", refresh_callback)

        assert result.access_token == "new-token"
        # Verify stored
        stored = store.get_credentials("server")
        assert stored.access_token == "new-token"


class TestMCPCredentialStoreBackendFallback:
    """Tests for backend selection and fallback."""

    def test_uses_file_backend_when_keyring_unavailable(self, tmp_path):
        """Test falls back to file backend when keyring unavailable."""
        with patch.dict("sys.modules", {"keyring": None}):
            store = MCPCredentialStore(fallback_dir=tmp_path)

        assert isinstance(store._backend, FileBackend)
