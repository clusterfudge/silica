"""Exceptions for Agent Island client."""


class IslandError(Exception):
    """Base exception for Agent Island errors."""


class ConnectionError(IslandError):
    """Failed to connect to Agent Island."""


class ProtocolError(IslandError):
    """Protocol-level error (invalid JSON-RPC, version mismatch, etc.)."""

    def __init__(self, message: str, code: int = -32603):
        super().__init__(message)
        self.code = code


class DialogNotFoundError(IslandError):
    """Referenced dialog does not exist."""

    def __init__(self, dialog_id: str):
        super().__init__(f"Dialog not found: {dialog_id}")
        self.dialog_id = dialog_id


class SessionNotFoundError(IslandError):
    """Session not registered."""

    def __init__(self, session_id: str):
        super().__init__(f"Session not found: {session_id}")
        self.session_id = session_id


class TimeoutError(IslandError):
    """Request timed out waiting for response."""
