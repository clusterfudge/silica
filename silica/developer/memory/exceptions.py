"""Custom exceptions for memory sync."""


class SyncError(Exception):
    """Base exception for sync errors."""


class SyncExhaustedError(SyncError):
    """Raised when sync fails after max retries."""


class SyncFatalError(SyncError):
    """Raised when a fatal error prevents sync from continuing."""
