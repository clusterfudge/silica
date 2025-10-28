"""Pytest fixtures for Memory Proxy tests."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws


@pytest.fixture
def mock_env_vars():
    """Mock environment variables for testing."""
    with patch.dict(
        os.environ,
        {
            "AWS_ACCESS_KEY_ID": "test-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret",
            "AWS_REGION": "us-east-1",
            "S3_BUCKET": "test-bucket",
            "S3_PREFIX": "memory",
            "HEARE_AUTH_URL": "http://test-auth",
            "HEARE_AUTH_APP_ID": "test-app",
            "LOG_LEVEL": "DEBUG",
        },
    ):
        yield


@pytest.fixture
def mock_s3(mock_env_vars):
    """Mock S3 with moto."""
    with mock_aws():
        # Create S3 client and bucket
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        yield s3


@pytest.fixture
def mock_auth_success():
    """Mock successful authentication."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"user_id": "test-user"}

    async def mock_post(*args, **kwargs):
        return mock_response

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=mock_post
        )
        yield mock_client


@pytest.fixture
def mock_auth_failure():
    """Mock failed authentication."""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Invalid token"

    async def mock_post(*args, **kwargs):
        return mock_response

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=mock_post
        )
        yield mock_client


@pytest.fixture
def test_client(mock_s3, mock_auth_success):
    """Create FastAPI test client with mocked dependencies."""
    # Import app after env vars are set
    from silica.memory_proxy.app import app
    from silica.memory_proxy.config import Settings
    from silica.memory_proxy.storage import S3Storage

    # Recreate storage with mocked S3
    settings = Settings()
    app.state.storage = S3Storage(settings)

    # Replace the module-level storage variable
    from silica.memory_proxy import app as app_module

    app_module.storage = app.state.storage

    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Authentication headers for test requests."""
    return {"Authorization": "Bearer test-token"}
