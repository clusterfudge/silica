"""Logging configuration for the cron application."""

import logging
import logging.config
import sys
from typing import Dict, Any
from pathlib import Path

from .settings import get_settings


def setup_logging() -> None:
    """Configure logging for the cron application."""
    settings = get_settings()

    # Create logs directory if file logging is enabled
    if settings.log_to_file:
        settings.log_dir.mkdir(exist_ok=True, parents=True)

    # Get log level from settings
    log_level = settings.log_level.upper()

    # Define logging configuration
    config = get_logging_config(log_level, settings.log_dir, settings.log_to_file)

    # Apply the configuration
    logging.config.dictConfig(config)

    # Set specific logger levels to reduce noise
    configure_third_party_loggers(log_level)


def get_logging_config(
    log_level: str, log_dir: Path, log_to_file: bool = True
) -> Dict[str, Any]:
    """Get the logging configuration dictionary."""
    settings = get_settings()

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "detailed": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "simple": {
                "format": "%(levelname)s - %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": log_level,
                "formatter": "simple" if settings.environment == "dev" else "default",
                "stream": sys.stdout,
            },
        },
    }

    # Add file handlers if enabled
    if log_to_file:
        config["handlers"]["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": log_level,
            "formatter": "detailed",
            "filename": str(log_dir / "cron.log"),
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "encoding": "utf8",
        }
        config["handlers"]["error_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "ERROR",
            "formatter": "detailed",
            "filename": str(log_dir / "cron-errors.log"),
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "encoding": "utf8",
        }

        # Update handler lists
        file_handlers = ["console", "file", "error_file"]
        file_only_handlers = ["file"]
    else:
        file_handlers = ["console"]
        file_only_handlers = ["console"]

    config["loggers"] = {
        # Root logger
        "": {
            "level": log_level,
            "handlers": file_handlers,
        },
        # Cron application loggers
        "silica.cron": {
            "level": log_level,
            "handlers": file_handlers,
            "propagate": False,
        },
        # Third-party loggers (reduced noise)
        "httpx": {
            "level": "WARNING",
            "handlers": file_only_handlers,
            "propagate": False,
        },
        "urllib3": {
            "level": "WARNING",
            "handlers": file_only_handlers,
            "propagate": False,
        },
        "requests": {
            "level": "WARNING",
            "handlers": file_only_handlers,
            "propagate": False,
        },
        "uvicorn": {
            "level": "INFO",
            "handlers": file_handlers,
            "propagate": False,
        },
        "uvicorn.access": {
            "level": "WARNING",  # Always suppress access logs by default
            "handlers": file_only_handlers,
            "propagate": False,
        },
        "fastapi": {
            "level": "INFO",
            "handlers": file_handlers,
            "propagate": False,
        },
        "sqlalchemy": {
            "level": "WARNING",
            "handlers": file_only_handlers,
            "propagate": False,
        },
        "sqlalchemy.engine": {
            "level": "WARNING",
            "handlers": file_only_handlers,
            "propagate": False,
        },
        "alembic": {
            "level": "INFO",
            "handlers": file_handlers,
            "propagate": False,
        },
    }

    # In development, be more verbose for our own code
    if settings.environment == "dev":
        config["loggers"]["silica.cron"]["level"] = "DEBUG"
        # Still suppress third-party noise
        config["loggers"]["httpx"]["level"] = "WARNING"
        config["loggers"]["urllib3"]["level"] = "WARNING"
        # Keep uvicorn.access suppressed even in dev

    return config


def configure_third_party_loggers(log_level: str) -> None:
    """Configure third-party loggers to reduce noise."""
    # Suppress noisy third-party loggers
    noisy_loggers = [
        "httpx",
        "urllib3",
        "urllib3.connectionpool",
        "requests.packages.urllib3",
        "botocore",
        "boto3",
        "s3transfer",
    ]

    for logger_name in noisy_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.WARNING)

    # Special handling for specific loggers
    settings = get_settings()

    # SQLAlchemy - only show warnings unless debug mode
    sqlalchemy_level = logging.DEBUG if log_level == "DEBUG" else logging.WARNING
    logging.getLogger("sqlalchemy").setLevel(sqlalchemy_level)
    logging.getLogger("sqlalchemy.engine").setLevel(sqlalchemy_level)

    # Uvicorn access logs - suppress in non-dev environments
    if settings.environment != "dev":
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the specified name."""
    return logging.getLogger(name)


def configure_test_logging() -> None:
    """Configure minimal logging for tests."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(name)s - %(levelname)s - %(message)s",
    )

    # Suppress all the noisy test loggers
    test_suppressions = [
        "httpx",
        "urllib3",
        "uvicorn",
        "uvicorn.access",
        "fastapi",
        "sqlalchemy",
        "sqlalchemy.engine",
    ]

    for logger_name in test_suppressions:
        logging.getLogger(logger_name).setLevel(logging.ERROR)
