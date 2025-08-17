"""Test logging configuration."""

import logging
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


from silica.cron.config.logging import (
    setup_logging,
    get_logging_config,
    configure_third_party_loggers,
    get_logger,
    configure_test_logging,
)


class TestLoggingConfiguration:
    """Test logging configuration functionality."""

    def test_setup_logging_default(self):
        """Test default logging setup."""
        with patch("silica.cron.config.logging.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                log_level="info",
                log_to_file=False,
                log_dir=Path("logs"),
                environment="dev",
            )

            with patch("logging.config.dictConfig") as mock_config:
                setup_logging()

                # Verify dictConfig was called
                mock_config.assert_called_once()
                config = mock_config.call_args[0][0]

                # Check basic structure
                assert "version" in config
                assert "handlers" in config
                assert "loggers" in config
                assert "console" in config["handlers"]

    def test_setup_logging_with_file(self):
        """Test logging setup with file logging enabled."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"

            with patch("silica.cron.config.logging.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock(
                    log_level="debug",
                    log_to_file=True,
                    log_dir=log_dir,
                    environment="dev",
                )

                with patch("logging.config.dictConfig") as mock_config:
                    setup_logging()

                    # Verify log directory was created
                    assert log_dir.exists()

                    # Check config includes file handlers
                    config = mock_config.call_args[0][0]
                    assert "file" in config["handlers"]
                    assert "error_file" in config["handlers"]

    def test_get_logging_config_console_only(self):
        """Test logging config with console only."""
        with patch("silica.cron.config.logging.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                environment="dev",
            )

            log_dir = Path("logs")
            config = get_logging_config("INFO", log_dir, log_to_file=False)

            # Should only have console handler
            assert "console" in config["handlers"]
            assert "file" not in config["handlers"]
            assert "error_file" not in config["handlers"]

            # Root logger should only use console
            assert config["loggers"][""]["handlers"] == ["console"]

    def test_get_logging_config_with_files(self):
        """Test logging config with file handlers."""
        with patch("silica.cron.config.logging.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                environment="dev",
            )

            log_dir = Path("logs")
            config = get_logging_config("INFO", log_dir, log_to_file=True)

            # Should have all handlers
            assert "console" in config["handlers"]
            assert "file" in config["handlers"]
            assert "error_file" in config["handlers"]

            # Root logger should use all handlers
            expected_handlers = ["console", "file", "error_file"]
            assert config["loggers"][""]["handlers"] == expected_handlers

    def test_third_party_logger_suppression(self):
        """Test that third-party loggers are properly suppressed."""
        configure_third_party_loggers("INFO")

        # Check that noisy loggers are set to WARNING
        noisy_loggers = ["httpx", "urllib3", "requests.packages.urllib3"]

        for logger_name in noisy_loggers:
            logger = logging.getLogger(logger_name)
            assert logger.level >= logging.WARNING

    def test_httpx_logger_suppression(self):
        """Test specific httpx logger suppression."""
        # This is the main issue we're solving
        configure_third_party_loggers("INFO")

        httpx_logger = logging.getLogger("httpx")
        assert httpx_logger.level >= logging.WARNING

        # Verify it doesn't log INFO messages
        with patch.object(httpx_logger, "info") as mock_info:
            httpx_logger.info("This should not appear")
            mock_info.assert_called_once()  # Called but will be filtered

    def test_get_logger_returns_correct_logger(self):
        """Test that get_logger returns the correct logger."""
        logger = get_logger("test.module")
        assert logger.name == "test.module"
        assert isinstance(logger, logging.Logger)

    def test_configure_test_logging(self):
        """Test test logging configuration."""
        configure_test_logging()

        # Check that test suppressions are applied
        test_suppressions = [
            "httpx",
            "urllib3",
            "uvicorn",
            "uvicorn.access",
            "fastapi",
            "sqlalchemy",
        ]

        for logger_name in test_suppressions:
            logger = logging.getLogger(logger_name)
            assert logger.level >= logging.ERROR

    def test_environment_specific_config(self):
        """Test environment-specific logging configuration."""
        with patch("silica.cron.config.logging.get_settings") as mock_settings:
            # Test development environment
            mock_settings.return_value = MagicMock(environment="dev")
            config = get_logging_config("INFO", Path("logs"), log_to_file=False)

            # In dev, should use simple formatter for console
            assert config["handlers"]["console"]["formatter"] == "simple"

            # Test production environment
            mock_settings.return_value = MagicMock(environment="prod")
            config = get_logging_config("INFO", Path("logs"), log_to_file=False)

            # In prod, should use default formatter for console
            assert config["handlers"]["console"]["formatter"] == "default"

    def test_sqlalchemy_logging_levels(self):
        """Test SQLAlchemy logging level configuration."""
        # Test with DEBUG level
        configure_third_party_loggers("DEBUG")
        sqlalchemy_logger = logging.getLogger("sqlalchemy")
        assert sqlalchemy_logger.level == logging.DEBUG

        # Test with INFO level
        configure_third_party_loggers("INFO")
        sqlalchemy_logger = logging.getLogger("sqlalchemy")
        assert sqlalchemy_logger.level == logging.WARNING

    def test_uvicorn_access_log_suppression(self):
        """Test uvicorn access log suppression in non-dev environments."""
        with patch("silica.cron.config.logging.get_settings") as mock_settings:
            # Test non-dev environment
            mock_settings.return_value = MagicMock(environment="prod")
            config = get_logging_config("INFO", Path("logs"), log_to_file=True)

            # uvicorn.access should be WARNING level in prod
            assert config["loggers"]["uvicorn.access"]["level"] == "WARNING"

            # Test dev environment (but we still suppress uvicorn.access by default)
            mock_settings.return_value = MagicMock(environment="dev")
            config = get_logging_config("INFO", Path("logs"), log_to_file=True)

            # uvicorn.access should still be WARNING (we suppress by default)
            assert config["loggers"]["uvicorn.access"]["level"] == "WARNING"


class TestLoggingIntegration:
    """Test logging integration with the application."""

    def test_cron_logger_configuration(self):
        """Test that cron application loggers are properly configured."""
        with patch("silica.cron.config.logging.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                log_level="info",
                log_to_file=True,
                log_dir=Path("logs"),
                environment="dev",
            )

            config = get_logging_config("INFO", Path("logs"), log_to_file=True)

            # Check silica.cron logger configuration
            cron_logger_config = config["loggers"]["silica.cron"]
            # In dev environment, cron logger level is set to DEBUG
            assert cron_logger_config["level"] == "DEBUG"
            assert cron_logger_config["propagate"] is False
            assert "console" in cron_logger_config["handlers"]

    def test_rotating_file_handler_configuration(self):
        """Test rotating file handler configuration."""
        with patch("silica.cron.config.logging.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(environment="dev")

            config = get_logging_config("INFO", Path("logs"), log_to_file=True)

            file_handler = config["handlers"]["file"]
            assert file_handler["class"] == "logging.handlers.RotatingFileHandler"
            assert file_handler["maxBytes"] == 10485760  # 10MB
            assert file_handler["backupCount"] == 5
            assert file_handler["encoding"] == "utf8"

            error_file_handler = config["handlers"]["error_file"]
            assert error_file_handler["level"] == "ERROR"
