"""Sync strategy interface and implementations for memory synchronization.

This module provides a clean dependency injection approach for memory sync,
allowing sync to be enabled/disabled without littering conditional checks
throughout the codebase.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SyncStrategy(ABC):
    """Abstract interface for memory synchronization strategies."""

    @abstractmethod
    def sync_after_flush(self, base_dir: Path, silent: bool = True) -> Optional[dict]:
        """Called after context flush to sync changes.

        Args:
            base_dir: Base directory that was flushed
            silent: If True, suppress user-facing messages (default for in-loop sync)

        Returns:
            Optional dict with sync results (for logging/debugging):
            {
                "succeeded": int,
                "failed": int,
                "conflicts": int,
                "error": str (if error occurred)
            }
        """

    @abstractmethod
    def sync_on_startup(self, base_dir: Path, silent: bool = False) -> Optional[dict]:
        """Called on agent startup to pull remote changes.

        Args:
            base_dir: Base directory to sync to
            silent: If False, show user-facing messages (default for startup)

        Returns:
            Optional dict with sync results (for logging/debugging)
        """


class NoOpSync(SyncStrategy):
    """No-op implementation - sync is disabled.

    This is used when memory sync is not configured or explicitly disabled.
    It provides zero overhead and no side effects.
    """

    def sync_after_flush(self, base_dir: Path, silent: bool = True) -> None:
        """No-op: does nothing."""
        return None

    def sync_on_startup(self, base_dir: Path, silent: bool = False) -> None:
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
        self.conflict_resolver = conflict_resolver

        # Lazy import to avoid circular dependencies
        if self.conflict_resolver is None:
            from silica.developer.memory.llm_conflict_resolver import (
                LLMConflictResolver,
            )

            self.conflict_resolver = LLMConflictResolver()

    def sync_after_flush(self, base_dir: Path, silent: bool = True) -> Optional[dict]:
        """Sync changes to remote after flush.

        Uses minimal retries (1) for fast path during agent loop.
        Failures are logged but don't interrupt the user.
        """
        try:
            from silica.developer.memory.sync import SyncEngine
            from silica.developer.memory.sync_coordinator import sync_with_retry

            engine = SyncEngine(
                client=self.client,
                local_base_dir=base_dir,
                namespace=self.namespace,
                conflict_resolver=self.conflict_resolver,
            )

            # Fast path: single retry, no progress bars
            result = sync_with_retry(engine, show_progress=False, max_retries=1)

            # Log failures but don't interrupt user
            if result.failed:
                logger.warning(
                    f"Sync after flush: {len(result.failed)} files failed to sync"
                )

            return {
                "succeeded": len(result.succeeded),
                "failed": len(result.failed),
                "conflicts": len(result.conflicts),
            }

        except Exception as e:
            logger.warning(f"Sync after flush failed: {e}")
            return {"error": str(e)}

    def sync_on_startup(self, base_dir: Path, silent: bool = False) -> Optional[dict]:
        """Sync from remote on startup.

        Uses full retries (3) since startup is allowed to take time.
        Shows user-facing messages by default.
        """
        try:
            from silica.developer.memory.sync import SyncEngine
            from silica.developer.memory.sync_coordinator import sync_with_retry

            engine = SyncEngine(
                client=self.client,
                local_base_dir=base_dir,
                namespace=self.namespace,
                conflict_resolver=self.conflict_resolver,
            )

            # Startup: full retries, no progress bars (but can show messages)
            result = sync_with_retry(engine, show_progress=False, max_retries=3)

            # Log warnings for failures
            if result.failed:
                logger.warning(
                    f"Sync on startup: {len(result.failed)} files failed to sync"
                )

            return {
                "succeeded": len(result.succeeded),
                "failed": len(result.failed),
                "conflicts": len(result.conflicts),
            }

        except Exception as e:
            logger.warning(f"Sync on startup failed: {e}")
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
        from silica.developer.memory.proxy_config import MemoryProxyConfig
        from silica.developer.memory.proxy_client import MemoryProxyClient

        # Check if sync is configured
        config = MemoryProxyConfig.load(base_dir)

        # If not configured or disabled, use no-op
        if not config or not config.is_enabled():
            return NoOpSync()

        # Extract namespace from base_dir path
        # e.g., ~/.silica/personas/default -> "default"
        namespace = "default"
        if base_dir:
            parts = Path(base_dir).parts
            if "personas" in parts:
                persona_idx = parts.index("personas")
                if persona_idx + 1 < len(parts):
                    namespace = parts[persona_idx + 1]

        # Create client and return remote sync
        client = MemoryProxyClient(config.url, config.token)
        return RemoteSync(client, namespace)

    except Exception as e:
        logger.warning(f"Failed to create sync strategy: {e}, using NoOpSync")
        return NoOpSync()
