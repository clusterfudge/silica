"""Tests for memory proxy HTTP client."""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import httpx

from silica.developer.memory.proxy_client import (
    MemoryProxyClient,
    VersionConflictError,
    NotFoundError,
    AuthenticationError,
    ConnectionError,
    SyncIndexResponse,
)


@pytest.fixture
def mock_httpx_client():
    """Mock httpx.Client for testing."""
    with patch("silica.developer.memory.proxy_client.httpx.Client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def proxy_client(mock_httpx_client):
    """Create a memory proxy client with mocked HTTP client."""
    return MemoryProxyClient(
        base_url="https://memory-proxy.example.com",
        token="test-token",
        timeout=10,
        max_retries=2,
    )


def test_client_initialization(proxy_client):
    """Test client is initialized correctly."""
    assert proxy_client.base_url == "https://memory-proxy.example.com"
    assert proxy_client.token == "test-token"
    assert proxy_client.timeout == 10
    assert proxy_client.max_retries == 2


def test_base_url_trailing_slash_removed():
    """Test that trailing slash is removed from base URL."""
    with patch("silica.developer.memory.proxy_client.httpx.Client"):
        client = MemoryProxyClient(
            base_url="https://memory-proxy.example.com/", token="test"
        )
        assert client.base_url == "https://memory-proxy.example.com"


def test_health_check_success(proxy_client, mock_httpx_client):
    """Test successful health check."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok", "storage": "connected"}
    mock_httpx_client.get.return_value = mock_response

    result = proxy_client.health_check()

    assert result is True
    mock_httpx_client.get.assert_called_once_with(
        "https://memory-proxy.example.com/health"
    )


def test_health_check_failure(proxy_client, mock_httpx_client):
    """Test health check failure."""
    mock_response = Mock()
    mock_response.status_code = 503
    mock_httpx_client.get.return_value = mock_response

    result = proxy_client.health_check()

    assert result is False


def test_health_check_exception(proxy_client, mock_httpx_client):
    """Test health check handles exceptions."""
    mock_httpx_client.get.side_effect = httpx.ConnectError("Connection refused")

    result = proxy_client.health_check()

    assert result is False


def test_read_blob_success(proxy_client, mock_httpx_client):
    """Test successful blob read."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = b"test content"
    mock_response.headers = {
        "ETag": '"abc123"',
        "Last-Modified": "Mon, 15 Jan 2025 10:30:00 GMT",
        "Content-Type": "text/markdown",
        "X-Version": "12345",
    }
    mock_httpx_client.get.return_value = mock_response

    content, md5, last_modified, content_type, version = proxy_client.read_blob(
        "default", "memory/test.md"
    )

    assert content == b"test content"
    assert md5 == "abc123"
    assert isinstance(last_modified, datetime)
    assert content_type == "text/markdown"
    assert version == 12345

    mock_httpx_client.get.assert_called_once_with(
        "https://memory-proxy.example.com/blob/default/memory/test.md"
    )


def test_read_blob_not_found(proxy_client, mock_httpx_client):
    """Test blob read when file not found."""
    mock_response = Mock()
    mock_response.status_code = 404
    mock_httpx_client.get.return_value = mock_response

    with pytest.raises(NotFoundError, match="File not found"):
        proxy_client.read_blob("default", "memory/missing.md")


def test_read_blob_auth_error(proxy_client, mock_httpx_client):
    """Test blob read with authentication error."""
    mock_response = Mock()
    mock_response.status_code = 401
    mock_httpx_client.get.return_value = mock_response

    with pytest.raises(AuthenticationError, match="Invalid authentication token"):
        proxy_client.read_blob("default", "memory/test.md")


def test_read_blob_connection_error(proxy_client, mock_httpx_client):
    """Test blob read with connection error."""
    mock_httpx_client.get.side_effect = httpx.ConnectError("Connection refused")

    with pytest.raises(ConnectionError, match="Failed to connect"):
        proxy_client.read_blob("default", "memory/test.md")


def test_write_blob_create_success(proxy_client, mock_httpx_client):
    """Test successful blob creation."""
    mock_response = Mock()
    mock_response.status_code = 201
    mock_response.headers = {
        "ETag": '"def456"',
        "X-Version": "12350",
    }
    mock_httpx_client.put.return_value = mock_response

    is_new, md5, version = proxy_client.write_blob(
        namespace="default",
        path="memory/new.md",
        content=b"new content",
        expected_version=0,
        content_type="text/markdown",
    )

    assert is_new is True
    assert md5 == "def456"
    assert version == 12350

    # Verify the request
    call_args = mock_httpx_client.put.call_args
    assert (
        call_args[0][0] == "https://memory-proxy.example.com/blob/default/memory/new.md"
    )
    assert call_args[1]["content"] == b"new content"
    assert call_args[1]["headers"]["If-Match-Version"] == "0"
    assert call_args[1]["headers"]["Content-Type"] == "text/markdown"


def test_write_blob_update_success(proxy_client, mock_httpx_client):
    """Test successful blob update."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {
        "ETag": '"ghi789"',
        "X-Version": "12360",
    }
    mock_httpx_client.put.return_value = mock_response

    is_new, md5, version = proxy_client.write_blob(
        namespace="default",
        path="memory/existing.md",
        content=b"updated content",
        expected_version=12350,
    )

    assert is_new is False
    assert md5 == "ghi789"
    assert version == 12360


def test_write_blob_version_conflict(proxy_client, mock_httpx_client):
    """Test blob write with version conflict."""
    mock_response = Mock()
    mock_response.status_code = 412
    mock_response.json.return_value = {
        "detail": "Version conflict",
        "error_code": "PRECONDITION_FAILED",
        "context": {
            "current_version": "12360",
            "provided_version": "12350",
        },
    }
    mock_httpx_client.put.return_value = mock_response

    with pytest.raises(VersionConflictError) as exc_info:
        proxy_client.write_blob(
            namespace="default",
            path="memory/conflict.md",
            content=b"conflicting content",
            expected_version=12350,
        )

    assert exc_info.value.current_version == 12360
    assert exc_info.value.provided_version == 12350


def test_write_blob_with_md5(proxy_client, mock_httpx_client):
    """Test blob write with MD5 validation."""
    mock_response = Mock()
    mock_response.status_code = 201
    mock_response.headers = {
        "ETag": '"abc123"',
        "X-Version": "12370",
    }
    mock_httpx_client.put.return_value = mock_response

    proxy_client.write_blob(
        namespace="default",
        path="memory/test.md",
        content=b"content",
        expected_version=0,
        content_md5="abc123",
    )

    call_args = mock_httpx_client.put.call_args
    assert call_args[1]["headers"]["Content-MD5"] == "abc123"


def test_delete_blob_success(proxy_client, mock_httpx_client):
    """Test successful blob deletion."""
    mock_response = Mock()
    mock_response.status_code = 204
    mock_httpx_client.delete.return_value = mock_response

    proxy_client.delete_blob("default", "memory/test.md", expected_version=12345)

    call_args = mock_httpx_client.delete.call_args
    assert (
        call_args[0][0]
        == "https://memory-proxy.example.com/blob/default/memory/test.md"
    )
    assert call_args[1]["headers"]["If-Match-Version"] == "12345"


def test_delete_blob_not_found(proxy_client, mock_httpx_client):
    """Test blob deletion when file not found."""
    mock_response = Mock()
    mock_response.status_code = 404
    mock_httpx_client.delete.return_value = mock_response

    with pytest.raises(NotFoundError, match="File not found"):
        proxy_client.delete_blob("default", "memory/missing.md")


def test_delete_blob_version_conflict(proxy_client, mock_httpx_client):
    """Test blob deletion with version conflict."""
    mock_response = Mock()
    mock_response.status_code = 412
    mock_response.json.return_value = {
        "detail": "Version conflict",
        "context": {
            "current_version": "12360",
            "provided_version": "12350",
        },
    }
    mock_httpx_client.delete.return_value = mock_response

    with pytest.raises(VersionConflictError):
        proxy_client.delete_blob("default", "memory/test.md", expected_version=12350)


def test_get_sync_index_success(proxy_client, mock_httpx_client):
    """Test successful sync index retrieval."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "files": {
            "memory/test.md": {
                "md5": "abc123",
                "last_modified": "2025-01-15T10:30:00Z",
                "size": 1024,
                "version": 12345,
                "is_deleted": False,
            },
            "persona.md": {
                "md5": "def456",
                "last_modified": "2025-01-15T09:00:00Z",
                "size": 2048,
                "version": 12000,
                "is_deleted": False,
            },
        },
        "index_last_modified": "2025-01-15T10:30:00Z",
        "index_version": 12345,
    }
    mock_httpx_client.get.return_value = mock_response

    result = proxy_client.get_sync_index("default")

    assert isinstance(result, SyncIndexResponse)
    assert len(result.files) == 2
    assert "memory/test.md" in result.files
    assert result.files["memory/test.md"].md5 == "abc123"
    assert result.files["memory/test.md"].version == 12345
    assert result.index_version == 12345

    mock_httpx_client.get.assert_called_once_with(
        "https://memory-proxy.example.com/sync/default"
    )


def test_get_sync_index_empty(proxy_client, mock_httpx_client):
    """Test sync index retrieval for empty namespace."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "files": {},
        "index_last_modified": "2025-01-15T10:30:00Z",
        "index_version": 0,
    }
    mock_httpx_client.get.return_value = mock_response

    result = proxy_client.get_sync_index("empty-persona")

    assert len(result.files) == 0


def test_context_manager():
    """Test client can be used as context manager."""
    with patch(
        "silica.developer.memory.proxy_client.httpx.Client"
    ) as mock_client_class:
        mock_client_instance = MagicMock()
        mock_client_class.return_value = mock_client_instance

        with MemoryProxyClient(base_url="https://test.com", token="test") as client:
            assert client is not None

        # Client should be closed after exiting context
        mock_client_instance.close.assert_called_once()


def test_close(proxy_client, mock_httpx_client):
    """Test client close method."""
    proxy_client.close()
    mock_httpx_client.close.assert_called_once()
