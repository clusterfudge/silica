"""Tests for sync strategy implementations."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch


from silica.developer.memory.sync_strategy import (
    NoOpSync,
    RemoteSync,
    SyncStrategy,
    create_sync_strategy,
)


class TestNoOpSync:
    """Test that NoOpSync does nothing."""

    def test_sync_returns_none(self):
        """Test that sync returns None."""
        strategy = NoOpSync()
        result = strategy.sync(Path("/fake/path"))
        assert result is None

    def test_sync_with_retries(self):
        """Test that sync accepts max_retries parameter."""
        strategy = NoOpSync()
        result = strategy.sync(Path("/fake/path"), max_retries=3)
        assert result is None

    def test_silent_parameter_accepted(self):
        """Test that silent parameter is accepted but ignored."""
        strategy = NoOpSync()
        result1 = strategy.sync(Path("/fake/path"), silent=True)
        result2 = strategy.sync(Path("/fake/path"), silent=False)
        assert result1 is None
        assert result2 is None


class TestRemoteSync:
    """Test RemoteSync implementation."""

    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        mock_client = Mock()
        mock_resolver = Mock()

        strategy = RemoteSync(
            client=mock_client,
            namespace="test-namespace",
            conflict_resolver=mock_resolver,
        )

        assert strategy.client is mock_client
        assert strategy.namespace == "test-namespace"
        assert strategy.conflict_resolver is mock_resolver

    def test_init_without_resolver(self):
        """Test initialization without resolver (should create default)."""
        mock_client = Mock()

        with patch(
            "silica.developer.memory.sync_strategy.LLMConflictResolver"
        ) as MockResolver:
            mock_resolver_instance = Mock()
            MockResolver.return_value = mock_resolver_instance

            strategy = RemoteSync(client=mock_client, namespace="test-namespace")

            MockResolver.assert_called_once()
            assert strategy.conflict_resolver is mock_resolver_instance

    @patch("silica.developer.memory.sync_strategy.SyncEngine")
    @patch("silica.developer.memory.sync_strategy.sync_with_retry")
    def test_sync_success(self, mock_sync_with_retry, mock_sync_engine):
        """Test successful sync."""
        mock_client = Mock()
        mock_resolver = Mock()

        # Mock the sync result
        mock_result = Mock()
        mock_result.succeeded = [Mock(), Mock(), Mock()]  # 3 succeeded
        mock_result.failed = []
        mock_result.conflicts = []
        mock_sync_with_retry.return_value = mock_result

        strategy = RemoteSync(mock_client, "test-namespace", mock_resolver)
        result = strategy.sync(Path("/fake/path"), max_retries=1, silent=True)

        # Verify SyncEngine was created with correct params
        mock_sync_engine.assert_called_once_with(
            client=mock_client,
            local_base_dir=Path("/fake/path"),
            namespace="test-namespace",
            conflict_resolver=mock_resolver,
        )

        # Verify sync_with_retry was called with correct params
        mock_sync_with_retry.assert_called_once()
        call_kwargs = mock_sync_with_retry.call_args.kwargs
        assert call_kwargs["show_progress"] is False
        assert call_kwargs["max_retries"] == 1

        # Verify result
        assert result == {
            "succeeded": 3,
            "failed": 0,
            "conflicts": 0,
        }

    @patch("silica.developer.memory.sync_strategy.SyncEngine")
    @patch("silica.developer.memory.sync_strategy.sync_with_retry")
    def test_sync_with_failures(self, mock_sync_with_retry, mock_sync_engine):
        """Test sync with some failures."""
        mock_client = Mock()
        mock_resolver = Mock()

        # Mock the sync result with failures
        mock_result = Mock()
        mock_result.succeeded = [Mock()]
        mock_result.failed = [Mock(), Mock()]  # 2 failed
        mock_result.conflicts = []
        mock_sync_with_retry.return_value = mock_result

        strategy = RemoteSync(mock_client, "test-namespace", mock_resolver)

        with patch("silica.developer.memory.sync_strategy.logger") as mock_logger:
            result = strategy.sync(Path("/fake/path"))

            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            assert "2 files failed" in str(mock_logger.warning.call_args)

        assert result == {
            "succeeded": 1,
            "failed": 2,
            "conflicts": 0,
        }

    @patch("silica.developer.memory.sync_strategy.SyncEngine")
    @patch("silica.developer.memory.sync_strategy.sync_with_retry")
    def test_sync_exception(self, mock_sync_with_retry, mock_sync_engine):
        """Test sync when exception occurs."""
        mock_client = Mock()
        mock_resolver = Mock()

        # Mock exception
        mock_sync_with_retry.side_effect = Exception("Network error")

        strategy = RemoteSync(mock_client, "test-namespace", mock_resolver)

        with patch("silica.developer.memory.sync_strategy.logger") as mock_logger:
            result = strategy.sync(Path("/fake/path"))

            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            assert "Network error" in str(mock_logger.warning.call_args)

        assert result == {"error": "Network error"}

    @patch("silica.developer.memory.sync_strategy.SyncEngine")
    @patch("silica.developer.memory.sync_strategy.sync_with_retry")
    def test_sync_with_custom_retries(self, mock_sync_with_retry, mock_sync_engine):
        """Test sync with custom max_retries."""
        mock_client = Mock()
        mock_resolver = Mock()

        # Mock the sync result
        mock_result = Mock()
        mock_result.succeeded = [Mock(), Mock()]
        mock_result.failed = []
        mock_result.conflicts = []
        mock_sync_with_retry.return_value = mock_result

        strategy = RemoteSync(mock_client, "test-namespace", mock_resolver)
        result = strategy.sync(Path("/fake/path"), max_retries=3, silent=False)

        # Verify sync_with_retry was called with custom params
        call_kwargs = mock_sync_with_retry.call_args.kwargs
        assert call_kwargs["show_progress"] is False
        assert call_kwargs["max_retries"] == 3

        assert result == {
            "succeeded": 2,
            "failed": 0,
            "conflicts": 0,
        }


class TestCreateSyncStrategy:
    """Test the factory function."""

    @patch("silica.developer.memory.sync_strategy.MemoryProxyConfig")
    def test_create_sync_strategy_no_config(self, MockConfig):
        """Test that NoOpSync is returned when no config exists."""
        # Mock config with no remote_url/auth_token (not configured)
        mock_config = Mock()
        mock_config.is_sync_enabled.return_value = False
        MockConfig.return_value = mock_config

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "personas" / "default"
            strategy = create_sync_strategy(base_dir)

            assert isinstance(strategy, NoOpSync)

    @patch("silica.developer.memory.sync_strategy.MemoryProxyConfig")
    @patch("silica.developer.memory.sync_strategy.MemoryProxyClient")
    def test_create_sync_strategy_config_disabled(self, MockClient, MockConfig):
        """Test that NoOpSync is returned when sync is disabled."""
        # Mock config that is disabled for this persona
        mock_config = Mock()
        mock_config.is_sync_enabled.return_value = False
        MockConfig.return_value = mock_config

        strategy = create_sync_strategy(Path("/fake/personas/test"))

        # Verify is_sync_enabled was called with persona name
        mock_config.is_sync_enabled.assert_called_once_with("test")
        assert isinstance(strategy, NoOpSync)

    @patch("silica.developer.memory.sync_strategy.MemoryProxyConfig")
    @patch("silica.developer.memory.sync_strategy.MemoryProxyClient")
    def test_create_sync_strategy_config_enabled(self, MockClient, MockConfig):
        """Test that RemoteSync is returned when sync is enabled."""
        # Mock config that is enabled for this persona
        mock_config = Mock()
        mock_config.is_sync_enabled.return_value = True
        mock_config.remote_url = "https://test-proxy.com"
        mock_config.auth_token = "test-token"
        MockConfig.return_value = mock_config

        # Mock client
        mock_client = Mock()
        MockClient.return_value = mock_client

        strategy = create_sync_strategy(Path("/fake/personas/test"))

        # Verify is_sync_enabled was called with persona name
        mock_config.is_sync_enabled.assert_called_once_with("test")

        # Verify client was created with correct params
        MockClient.assert_called_once_with("https://test-proxy.com", "test-token")

        # Verify RemoteSync was created
        assert isinstance(strategy, RemoteSync)
        assert strategy.client is mock_client
        assert strategy.namespace == "test"  # Extracted from path

    @patch("silica.developer.memory.sync_strategy.MemoryProxyConfig")
    def test_create_sync_strategy_exception(self, MockConfig):
        """Test that NoOpSync is returned when exception occurs."""
        # Mock exception during config creation
        MockConfig.side_effect = Exception("Config error")

        with patch("silica.developer.memory.sync_strategy.logger") as mock_logger:
            strategy = create_sync_strategy(Path("/fake/path"))

            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            assert "Failed to create sync strategy" in str(
                mock_logger.warning.call_args
            )

        assert isinstance(strategy, NoOpSync)

    @patch("silica.developer.memory.sync_strategy.MemoryProxyConfig")
    @patch("silica.developer.memory.sync_strategy.MemoryProxyClient")
    def test_namespace_extraction(self, MockClient, MockConfig):
        """Test namespace extraction from various paths."""
        # Mock config
        mock_config = Mock()
        mock_config.is_sync_enabled.return_value = True
        mock_config.remote_url = "https://test.com"
        mock_config.auth_token = "token"
        MockConfig.return_value = mock_config
        MockClient.return_value = Mock()

        # Test various path formats
        test_cases = [
            (Path("/home/user/.silica/personas/default"), "default"),
            (Path("/home/user/.silica/personas/my-persona"), "my-persona"),
            (Path("/Users/john/.silica/personas/work"), "work"),
            (Path("/some/other/path"), "default"),  # Fallback
        ]

        for path, expected_namespace in test_cases:
            strategy = create_sync_strategy(path)
            assert strategy.namespace == expected_namespace


class TestSyncStrategyInterface:
    """Test that both implementations satisfy the interface."""

    def test_noop_implements_interface(self):
        """Test that NoOpSync implements SyncStrategy."""
        strategy = NoOpSync()
        assert isinstance(strategy, SyncStrategy)
        assert hasattr(strategy, "sync")

    def test_remote_implements_interface(self):
        """Test that RemoteSync implements SyncStrategy."""
        mock_client = Mock()
        strategy = RemoteSync(mock_client, "test")
        assert isinstance(strategy, SyncStrategy)
        assert hasattr(strategy, "sync")
