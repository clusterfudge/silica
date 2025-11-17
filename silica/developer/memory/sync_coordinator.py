"""Sync coordinator with retry and conflict resolution logic."""

import logging
from typing import Any

from .sync import SyncEngine, SyncResult
from .exceptions import SyncExhaustedError, SyncFatalError
from .conflict_resolver import ConflictResolutionError
from .proxy_client import (
    VersionConflictError,
    NotFoundError,
    AuthenticationError,
    MemoryProxyError,
)

logger = logging.getLogger(__name__)


def sync_with_retry(
    sync_engine: SyncEngine,
    max_retries: int = 3,
    show_progress: bool = True,
) -> SyncResult:
    """Coordinate sync with automatic conflict resolution and retries.

    This function implements the retry logic for syncing:
    1. Analyze what needs syncing
    2. If conflicts exist, resolve them via LLM merge
    3. Execute the sync plan
    4. If errors occur, classify them as fatal or retryable
    5. For retryable errors (version conflicts, network issues), retry
    6. For fatal errors (auth, permissions), fail immediately
    7. Repeat until success or max_retries exhausted

    Args:
        sync_engine: SyncEngine instance (should have conflict_resolver configured)
        max_retries: Maximum number of retry attempts (default: 3)
        show_progress: Whether to show progress during sync (default: True)

    Returns:
        Final SyncResult with all operations completed

    Raises:
        SyncExhaustedError: If max retries exceeded without success
        SyncFatalError: If fatal error encountered (auth, permissions, etc.)
        ValueError: If sync_engine has no conflict_resolver configured
    """
    if not sync_engine.conflict_resolver:
        raise ValueError(
            "SyncEngine must have a conflict_resolver configured for sync_with_retry. "
            "Pass a ConflictResolver instance to SyncEngine.__init__."
        )

    for attempt in range(1, max_retries + 1):
        logger.info(f"Sync attempt {attempt}/{max_retries}")

        try:
            # Analyze what needs syncing
            plan = sync_engine.analyze_sync_operations()

            # Handle conflicts
            if plan.has_conflicts:
                logger.info(
                    f"Detected {len(plan.conflicts)} conflicts, resolving via LLM merge"
                )

                try:
                    # Resolve conflicts and get upload operations
                    resolved_uploads = sync_engine.resolve_conflicts(plan.conflicts)

                    # Replace conflicts with resolved uploads
                    plan.conflicts = []
                    plan.upload.extend(resolved_uploads)

                    logger.info(
                        f"Successfully resolved conflicts, "
                        f"added {len(resolved_uploads)} uploads to plan"
                    )

                except ConflictResolutionError as e:
                    logger.error(
                        f"Conflict resolution failed for {sync_engine.namespace}: {e}"
                    )
                    if is_fatal_error(e):
                        raise SyncFatalError(
                            f"Fatal error during conflict resolution: {e}"
                        ) from e
                    # Retryable - continue to next attempt
                    logger.info("Conflict resolution error is retryable, will retry")
                    continue

            # If nothing to do, we're done!
            if plan.total_operations == 0:
                logger.info("Sync complete - everything in sync")
                return SyncResult(succeeded=[], failed=[], conflicts=[], skipped=[])

            # Execute the plan
            logger.info(
                f"Executing sync plan: {plan.total_operations} operations "
                f"(uploads={len(plan.upload)}, downloads={len(plan.download)}, "
                f"deletes={len(plan.delete_local) + len(plan.delete_remote)})"
            )

            result = sync_engine.execute_sync(plan, show_progress=show_progress)

            # Check for errors
            if result.failed:
                logger.warning(
                    f"{len(result.failed)} operations failed, "
                    f"success rate: {result.success_rate:.1f}%"
                )

                # Classify errors
                fatal_failures = [op for op in result.failed if _is_fatal_failure(op)]

                if fatal_failures:
                    paths = [op.path for op in fatal_failures]
                    raise SyncFatalError(
                        f"Fatal errors during sync: {len(fatal_failures)} operations failed. "
                        f"Files: {paths}"
                    )

                # All failures are retryable - re-plan and retry
                logger.info(
                    f"All {len(result.failed)} failures are retryable, "
                    f"will re-plan and retry"
                )
                continue

            # Success!
            if result.success_rate == 100.0:
                logger.info(
                    f"Sync successful: {len(result.succeeded)} operations completed "
                    f"in {result.duration:.2f}s"
                )
                return result

        except VersionConflictError as e:
            # Version conflict (412) means our index is stale
            # This is retryable - just re-analyze
            logger.warning(
                f"Version conflict detected (attempt {attempt}/{max_retries}): {e}"
            )
            logger.info("Re-analyzing sync state after version conflict")
            continue

        except (AuthenticationError, PermissionError, OSError) as e:
            # Fatal errors - don't retry
            logger.error(f"Fatal error during sync for {sync_engine.namespace}: {e}")
            raise SyncFatalError(f"Fatal error during sync: {e}") from e

        except ValueError as e:
            # Likely unresolved conflicts in execute_sync
            logger.error(f"Invalid sync state for {sync_engine.namespace}: {e}")
            raise SyncFatalError(f"Invalid sync state: {e}") from e

        except Exception as e:
            # Unknown error - classify it
            logger.error(
                f"Unexpected error during sync for {sync_engine.namespace}: {e}"
            )
            if is_fatal_error(e):
                raise SyncFatalError(f"Fatal error during sync: {e}") from e

            # Otherwise retry
            logger.warning(
                f"Error is retryable (attempt {attempt}/{max_retries}), will retry"
            )
            continue

    # Max retries exceeded
    logger.error(
        f"Sync failed for {sync_engine.namespace} after {max_retries} attempts"
    )
    raise SyncExhaustedError(
        f"Sync failed after {max_retries} attempts. "
        f"Please check logs and try again later."
    )


def is_fatal_error(e: Exception) -> bool:
    """Determine if an error is fatal (don't retry).

    Fatal errors:
    - Authentication failures
    - Permission errors
    - File system errors (disk full, etc.)

    Retryable errors:
    - Version conflicts (412) - index is stale, re-plan
    - Network errors - transient
    - Rate limiting - transient

    Args:
        e: Exception to classify

    Returns:
        True if error is fatal, False if retryable
    """
    # Auth errors are fatal
    if isinstance(e, AuthenticationError):
        return True

    # File system errors are fatal
    if isinstance(e, (PermissionError, OSError)):
        return True

    # Version conflicts are retryable (just need to re-plan)
    if isinstance(e, VersionConflictError):
        return False

    # Network/connection errors are retryable
    if isinstance(e, ConnectionError):
        return False

    # Memory proxy errors - check if it's a client error (4xx) vs server error (5xx)
    # Server errors (5xx) are retryable, client errors (4xx, except 412) are fatal
    if isinstance(e, MemoryProxyError):
        error_msg = str(e)
        if "412" in error_msg:  # Version conflict
            return False
        if any(code in error_msg for code in ["500", "502", "503", "504"]):
            return False  # Server errors are retryable
        return True  # Other client errors are fatal

    # Conflict resolution errors are retryable (LLM might have temp issues)
    if isinstance(e, ConflictResolutionError):
        return False

    # NotFoundError is fatal (file was deleted during sync)
    if isinstance(e, NotFoundError):
        return True

    # Default: assume fatal for safety
    return True


def _is_fatal_failure(op: Any) -> bool:
    """Check if a failed operation represents a fatal error.

    Args:
        op: SyncOperationDetail from result.failed

    Returns:
        True if the failure is fatal
    """
    # For now, all failures in the result are considered retryable
    # since fatal errors would have been raised as exceptions
    # We could enhance this by storing the exception type in the operation
    return False
