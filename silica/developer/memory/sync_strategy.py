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

    def __init__(
        self,
        client,
        namespace: str,
        conflict_resolver=None,
        scan_base: Path | None = None,
    ):
        """Initialize remote sync.

        Args:
            client: MemoryProxyClient instance
            namespace: Namespace for remote storage (e.g., "default/memory")
            conflict_resolver: ConflictResolver instance (optional, defaults to LLM)
            scan_base: Base directory to scan files from (optional, relative to persona base)
        """
        self.client = client
        self.namespace = namespace
        self.conflict_resolver = conflict_resolver or LLMConflictResolver()
        self.scan_base = scan_base

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
            # Calculate actual scan_base path if relative path provided
            scan_base_path = base_dir / self.scan_base if self.scan_base else base_dir

            engine = SyncEngine(
                client=self.client,
                local_base_dir=base_dir,
                namespace=self.namespace,
                conflict_resolver=self.conflict_resolver,
                scan_base=scan_base_path,
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


def create_sync_strategies(
    base_dir: Path, session_id: str | None = None
) -> tuple[SyncStrategy, SyncStrategy]:
    """Factory function to create sync strategies for memory and history.

    Checks configuration and returns appropriate strategies for:
    1. Memory sync (memory/ and persona.md)
    2. Session history sync (history/session_id/) - only if session_id provided

    Args:
        base_dir: Base directory for persona (e.g., ~/.silica/personas/default)
        session_id: Optional session ID for history sync

    Returns:
        Tuple of (memory_strategy, history_strategy)
        - memory_strategy: RemoteSync or NoOpSync for memory
        - history_strategy: RemoteSync or NoOpSync for this session's history
    """
    try:
        # Load global config
        config = MemoryProxyConfig()

        # Extract namespace (persona name) from base_dir path
        # e.g., ~/.silica/personas/default -> "default"
        persona_name = "default"
        if base_dir:
            parts = Path(base_dir).parts
            if "personas" in parts:
                persona_idx = parts.index("personas")
                if persona_idx + 1 < len(parts):
                    persona_name = parts[persona_idx + 1]

        # Check if sync is enabled for this persona
        if not config.is_sync_enabled(persona_name):
            return NoOpSync(), NoOpSync()

        # Create client
        client = MemoryProxyClient(config.remote_url, config.auth_token)

        # Create memory sync strategy - scans from memory/ directory
        memory_strategy = RemoteSync(
            client=client,
            namespace=f"{persona_name}/memory",
            scan_base=Path("memory"),  # Relative to base_dir
        )

        # Create session history sync strategy if session_id provided
        if session_id:
            history_strategy = RemoteSync(
                client=client,
                namespace=f"{persona_name}/history/{session_id}",
                scan_base=Path("history") / session_id,  # Relative to base_dir
            )
        else:
            history_strategy = NoOpSync()

        return memory_strategy, history_strategy

    except Exception as e:
        logger.warning(f"Failed to create sync strategies: {e}, using NoOpSync")
        return NoOpSync(), NoOpSync()


def create_sync_strategy(base_dir: Path) -> SyncStrategy:
    """Legacy factory function - creates only memory sync strategy.

    DEPRECATED: Use create_sync_strategies() instead for separate memory/history sync.

    Args:
        base_dir: Base directory for persona

    Returns:
        SyncStrategy instance for memory only
    """
    memory_strategy, _ = create_sync_strategies(base_dir, session_id=None)
    return memory_strategy
