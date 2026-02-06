"""E2E test configuration and helpers.

Reads deaddrop configuration from ~/.config/deadrop/config.yaml
and provides utilities for E2E testing.
"""

import os
import uuid
import yaml
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

from deadrop import Deaddrop


@dataclass
class DeaddropConfig:
    """Deaddrop configuration."""

    url: str
    bearer_token: Optional[str] = None


def load_deaddrop_config() -> DeaddropConfig:
    """Load deaddrop configuration from ~/.config/deadrop/config.yaml.

    Returns:
        DeaddropConfig with url and optional bearer_token

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    config_path = Path.home() / ".config" / "deadrop" / "config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Deaddrop config not found at {config_path}. "
            "Create it with 'url' and optionally 'bearer_token' fields."
        )

    with open(config_path) as f:
        config = yaml.safe_load(f)

    if not config or "url" not in config:
        raise ValueError(f"Invalid config at {config_path}: missing 'url' field")

    return DeaddropConfig(
        url=config["url"],
        bearer_token=config.get("bearer_token"),
    )


def get_remote_deaddrop() -> Deaddrop:
    """Get a Deaddrop client connected to the remote server.

    Returns:
        Deaddrop client configured for remote server
    """
    config = load_deaddrop_config()
    return Deaddrop.remote(url=config.url, bearer_token=config.bearer_token)


def get_local_deaddrop(port: int = 8765) -> Deaddrop:
    """Get a Deaddrop client connected to a local server.

    The local server should be started with DEADROP_NO_AUTH=1 for E2E tests.

    Args:
        port: Port the local server is running on (default 8765)

    Returns:
        Deaddrop client configured for local server
    """
    return Deaddrop.remote(url=f"http://127.0.0.1:{port}")


# Default to local for E2E tests (has rooms support)
LOCAL_DEADDROP_PORT = int(os.environ.get("DEADDROP_PORT", "8765"))


def get_e2e_deaddrop() -> Deaddrop:
    """Get the Deaddrop client for E2E tests.

    Uses local server by default (for rooms support).
    Set DEADDROP_E2E_REMOTE=1 to use remote instead.

    Returns:
        Deaddrop client
    """
    if os.environ.get("DEADDROP_E2E_REMOTE"):
        return get_remote_deaddrop()
    return get_local_deaddrop(LOCAL_DEADDROP_PORT)


@contextmanager
def test_namespace(deaddrop: Deaddrop, prefix: str = "e2e-test"):
    """Context manager that creates a test namespace and cleans up.

    Args:
        deaddrop: Deaddrop client
        prefix: Prefix for namespace name

    Yields:
        Dict with namespace info (ns, secret, etc.)
    """
    # Create namespace
    name = f"{prefix}-{uuid.uuid4().hex[:8]}"
    ns = deaddrop.create_namespace(display_name=name)

    try:
        yield ns
    finally:
        # Clean up - archive the namespace
        try:
            deaddrop.archive_namespace(ns=ns["ns"], secret=ns["secret"])
        except Exception as e:
            print(f"Warning: Failed to clean up namespace {ns['ns']}: {e}")


def print_config():
    """Print current deaddrop configuration."""
    try:
        config = load_deaddrop_config()
        print(f"Deaddrop URL: {config.url}")
        print(f"Bearer token: {'configured' if config.bearer_token else 'not set'}")
    except Exception as e:
        print(f"Error loading config: {e}")


if __name__ == "__main__":
    print_config()
