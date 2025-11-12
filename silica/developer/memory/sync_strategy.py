"""Sync strategy interface and implementations for memory synchronization.

This module provides a clean dependency injection approach for memory sync,
allowing sync to be enabled/disabled without littering conditional checks
throughout the codebase.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from silica.developer.memory.llm_conflict_resolver import LLMConflictResolver
from silica.developer.memory.proxy_client import MemoryProxyClient
from silica.developer.memory.proxy_config import MemoryProxyConfig
from silica.developer.memory.sync import SyncEngine
from silica.developer.memory.sync_coordinator import sync_with_retry

logger = logging.getLogger(__name__)


class SyncStrategy(ABC):
    """Abstract interface for memory synchronization strategies."""

    @abstractmethod
    def sync(
        self, base_dir: Path, max_retries: int = 1, silent: bool = True
    ) -> Optional[dict]:
        """Sync local and remote memory.

        Args:
            base_dir: Base directory to sync
            max_retries: Maximum number of retry attempts (default: 1 for fast path)
            silent: If True, suppress user-facing messages (default: True)

        Returns:
            Optional dict with sync results (for logging/debugging):
            {
                "succeeded": int,
                "failed": int,
                "conflicts": int,
                "error": str (if error occurred)
            }
        """


class NoOpSync(SyncStrategy):
    """No-op implementation - sync is disabled.

    This is used when memory sync is not configured or explicitly disabled.
    It provides zero overhead and no side effects.
    """

    def sync(self, base_dir: Path, max_retries: int = 1, silent: bool = True) -> None:
        """No-op: does nothing."""
        return None


class RemoteSync(SyncStrategy):
    """Real implementation that syncs to remote storage via memory proxy."""

    def __init__(self, client, namespace: str, conflict_resolver=None):
        """Initialize remote sync.

        Args:
            client: MemoryProxyClient instance
            namespace: Namespace for remote storage (typically persona name)
            conflict_resolver: ConflictResolver instance (optional, defaults to LLM)
        """
        self.client = client
        self.namespace = namespace
        self.conflict_resolver = conflict_resolver or LLMConflictResolver()

    def sync(
        self, base_dir: Path, max_retries: int = 1, silent: bool = True
    ) -> Optional[dict]:
        """Sync local and remote memory.

        Args:
            base_dir: Base directory to sync
            max_retries: Maximum number of retry attempts
            silent: If True, suppress user-facing messages

        Returns:
            Dict with sync results
        """
        try:
            engine = SyncEngine(
                client=self.client,
                local_base_dir=base_dir,
                namespace=self.namespace,
                conflict_resolver=self.conflict_resolver,
            )

            result = sync_with_retry(
                engine, show_progress=False, max_retries=max_retries
            )

            # Log failures but don't interrupt user
            if result.failed:
                logger.warning(f"Sync: {len(result.failed)} files failed to sync")

            return {
                "succeeded": len(result.succeeded),
                "failed": len(result.failed),
                "conflicts": len(result.conflicts),
            }

        except Exception as e:
            logger.warning(f"Sync failed: {e}")
            return {"error": str(e)}


def create_sync_strategy(base_dir: Path) -> SyncStrategy:
    """Factory function to create appropriate sync strategy.

    Checks configuration and returns either RemoteSync or NoOpSync
    based on whether sync is configured and enabled.

    Args:
        base_dir: Base directory for persona (e.g., ~/.silica/personas/default)

    Returns:
        SyncStrategy instance (RemoteSync if enabled, NoOpSync otherwise)
    """
    try:
        # Load global config
        config = MemoryProxyConfig()

        # Extract namespace (persona name) from base_dir path
        # e.g., ~/.silica/personas/default -> "default"
        namespace = "default"
        if base_dir:
            parts = Path(base_dir).parts
            if "personas" in parts:
                persona_idx = parts.index("personas")
                if persona_idx + 1 < len(parts):
                    namespace = parts[persona_idx + 1]

        # Check if sync is enabled for this persona
        if not config.is_sync_enabled(namespace):
            return NoOpSync()

        # Create client and return remote sync
        client = MemoryProxyClient(config.remote_url, config.auth_token)
        return RemoteSync(client, namespace)

    except Exception as e:
        logger.warning(f"Failed to create sync strategy: {e}, using NoOpSync")
        return NoOpSync()
