"""Coordination context helper for deaddrop communication.

Provides convenience methods that combine Deaddrop operations with
message protocol serialization and compression. This is NOT a wrapper -
it uses Deaddrop directly and adds coordination-specific logic on top.

Includes error recovery:
- Retry with exponential backoff for connection failures
- Skip and log for message parse errors
- Graceful degradation for transient failures
"""

from dataclasses import dataclass, field
from functools import wraps
import json
import logging
import random
import time
from typing import Any, Callable, Optional, TypeVar

from deadrop import Deaddrop

from .compression import compress_payload, decompress_payload
from .protocol import (
    COORDINATION_CONTENT_TYPE,
    CoordinationMessage,
    deserialize_message,
    serialize_message,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DeaddropConnectionError(Exception):
    """Raised when deaddrop connection fails after retries."""


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator that adds retry with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (default 3)
        base_delay: Initial delay in seconds (default 1.0)
        max_delay: Maximum delay in seconds (default 30.0)
        exponential_base: Base for exponential backoff (default 2.0)
        jitter: Add randomness to prevent thundering herd (default True)

    Returns:
        Decorated function with retry logic
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Optional[Exception] = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        delay = min(base_delay * (exponential_base**attempt), max_delay)
                        if jitter:
                            delay *= 0.5 + random.random()
                        logger.warning(
                            f"Deaddrop operation failed (attempt {attempt + 1}/{max_attempts}): {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"Deaddrop operation failed after {max_attempts} attempts: {e}"
                        )
            # If we get here, all retries failed
            raise DeaddropConnectionError(
                f"Operation failed after {max_attempts} attempts"
            ) from last_exception

        return wrapper

    return decorator


@dataclass
class ReceivedMessage:
    """A received message with metadata."""

    message: CoordinationMessage
    from_id: str
    mid: str  # Message ID for tracking
    is_room_message: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


class CoordinationContext:
    """Context for coordination communication via deaddrop.

    Holds connection state and provides convenience methods for sending
    and receiving coordination protocol messages.
    """

    def __init__(
        self,
        deaddrop: Deaddrop,
        namespace_id: str,
        namespace_secret: str,
        identity_id: str,
        identity_secret: str,
        room_id: Optional[str] = None,
        coordinator_id: Optional[str] = None,
    ):
        """Initialize coordination context.

        Args:
            deaddrop: Deaddrop client instance
            namespace_id: The coordination namespace ID
            namespace_secret: Secret for namespace-level operations
            identity_id: This participant's identity ID
            identity_secret: This participant's identity secret
            room_id: Optional coordination room ID for broadcasts
            coordinator_id: Optional coordinator identity ID (for workers)
        """
        self.deaddrop = deaddrop
        self.namespace_id = namespace_id
        self.namespace_secret = namespace_secret
        self.identity_id = identity_id
        self.identity_secret = identity_secret
        self.room_id = room_id
        self.coordinator_id = coordinator_id

        # Track last seen message IDs for polling
        self._last_inbox_mid: Optional[str] = None
        self._last_room_mid: Optional[str] = None

    def send_message(
        self,
        to_id: str,
        message: CoordinationMessage,
        retry: bool = True,
    ) -> dict[str, Any]:
        """Send a coordination message to a specific identity.

        Args:
            to_id: Recipient identity ID
            message: Message dataclass to send
            retry: Whether to retry on connection failure (default True)

        Returns:
            Deaddrop send result

        Raises:
            DeaddropConnectionError: If all retries fail (when retry=True)
        """
        body, compression = self._serialize_with_compression(message)
        content_type = self._content_type_with_compression(compression)

        def _send() -> dict[str, Any]:
            return self.deaddrop.send_message(
                ns=self.namespace_id,
                from_secret=self.identity_secret,
                to_id=to_id,
                body=body,
                content_type=content_type,
            )

        if retry:
            return with_retry()(_send)()
        return _send()

    def send_to_coordinator(
        self, message: CoordinationMessage, retry: bool = True
    ) -> dict[str, Any]:
        """Send a message to the coordinator (convenience for workers).

        Args:
            message: Message to send
            retry: Whether to retry on connection failure (default True)

        Returns:
            Deaddrop send result

        Raises:
            ValueError: If coordinator_id not set
            DeaddropConnectionError: If all retries fail (when retry=True)
        """
        if not self.coordinator_id:
            raise ValueError("coordinator_id not set - cannot send to coordinator")
        return self.send_message(self.coordinator_id, message, retry=retry)

    def broadcast(
        self, message: CoordinationMessage, retry: bool = True
    ) -> dict[str, Any]:
        """Broadcast a message to the coordination room.

        Args:
            message: Message to broadcast
            retry: Whether to retry on connection failure (default True)

        Returns:
            Deaddrop send result

        Raises:
            ValueError: If room_id not set
            DeaddropConnectionError: If all retries fail (when retry=True)
        """
        if not self.room_id:
            raise ValueError("room_id not set - cannot broadcast")

        body, compression = self._serialize_with_compression(message)
        content_type = self._content_type_with_compression(compression)

        def _broadcast() -> dict[str, Any]:
            return self.deaddrop.send_room_message(
                ns=self.namespace_id,
                room_id=self.room_id,
                secret=self.identity_secret,
                body=body,
                content_type=content_type,
            )

        if retry:
            return with_retry()(_broadcast)()
        return _broadcast()

    def receive_messages(
        self,
        include_room: bool = True,
        retry: bool = True,
    ) -> list[ReceivedMessage]:
        """Receive new messages from inbox and optionally room.

        Returns immediately with any new messages since the last call.
        Skips messages that fail to parse (logs warning).
        Retries on connection failure if retry=True.

        Args:
            include_room: Whether to also check the coordination room
            retry: Whether to retry on connection failure (default True)

        Returns:
            List of received messages, newest first

        Raises:
            DeaddropConnectionError: If all retries fail (when retry=True)
        """
        messages = []

        def _get_inbox() -> list[dict[str, Any]]:
            return self.deaddrop.get_inbox(
                ns=self.namespace_id,
                identity_id=self.identity_id,
                secret=self.identity_secret,
                after_mid=self._last_inbox_mid,
            )

        # Get inbox messages with optional retry
        try:
            if retry:
                inbox_messages = with_retry()(_get_inbox)()
            else:
                inbox_messages = _get_inbox()
        except DeaddropConnectionError:
            logger.warning("Failed to get inbox messages, continuing with empty")
            inbox_messages = []

        for raw in inbox_messages:
            try:
                msg = self._parse_message(raw)
                if msg:
                    msg.is_room_message = False
                    messages.append(msg)
                    self._last_inbox_mid = raw.get("mid")
                else:
                    # Update cursor even if we couldn't parse (skip bad messages)
                    mid = raw.get("mid")
                    if mid:
                        self._last_inbox_mid = mid
            except Exception as e:
                logger.warning(f"Failed to parse inbox message: {e}")
                # Still update cursor to skip this message
                mid = raw.get("mid")
                if mid:
                    self._last_inbox_mid = mid

        # Get room messages if requested and room is set
        if include_room and self.room_id:

            def _get_room() -> list[dict[str, Any]]:
                return self.deaddrop.get_room_messages(
                    ns=self.namespace_id,
                    room_id=self.room_id,
                    secret=self.identity_secret,
                    after_mid=self._last_room_mid,
                )

            try:
                if retry:
                    room_messages = with_retry()(_get_room)()
                else:
                    room_messages = _get_room()
            except DeaddropConnectionError:
                logger.warning("Failed to get room messages, continuing with empty")
                room_messages = []

            for raw in room_messages:
                try:
                    msg = self._parse_message(raw)
                    if msg:
                        msg.is_room_message = True
                        messages.append(msg)
                        self._last_room_mid = raw.get("mid")
                    else:
                        mid = raw.get("mid")
                        if mid:
                            self._last_room_mid = mid
                except Exception as e:
                    logger.warning(f"Failed to parse room message: {e}")
                    mid = raw.get("mid")
                    if mid:
                        self._last_room_mid = mid

        return messages

    def wait_for_messages(
        self,
        timeout: float = 30,
        include_room: bool = True,
    ) -> list[ReceivedMessage]:
        """Block until new messages arrive, then return them.

        For remote backends, uses deaddrop's subscribe() with server-side
        event notification (wakes instantly when a message is published).
        For local backends, polls the database with a short interval.

        Args:
            timeout: Max seconds to wait (default 30)
            include_room: Whether to also watch the coordination room

        Returns:
            List of received messages (empty if timeout with no messages)
        """
        from deadrop.backends import LocalBackend

        if isinstance(self.deaddrop._backend, LocalBackend):
            return self._wait_for_messages_poll(timeout, include_room)
        return self._wait_for_messages_subscribe(timeout, include_room)

    def _wait_for_messages_subscribe(
        self,
        timeout: float,
        include_room: bool,
    ) -> list[ReceivedMessage]:
        """Wait using subscribe() — for remote backends with server-side events."""
        # Build topic vector clock from our cursors
        topics: dict[str, str | None] = {
            f"inbox:{self.identity_id}": self._last_inbox_mid,
        }
        if include_room and self.room_id:
            topics[f"room:{self.room_id}"] = self._last_room_mid

        try:
            result = self.deaddrop.subscribe(
                ns=self.namespace_id,
                secret=self.identity_secret,
                topics=topics,
                timeout=max(1, min(timeout, 60)),
            )
        except Exception as e:
            logger.warning(f"Subscribe failed, falling back to immediate fetch: {e}")
            return self.receive_messages(include_room=include_room)

        # If timed out with no events, return empty
        if result.get("timeout"):
            return []

        # Events arrived — fetch the actual messages
        return self.receive_messages(include_room=include_room)

    def _wait_for_messages_poll(
        self,
        timeout: float,
        include_room: bool,
    ) -> list[ReceivedMessage]:
        """Wait using polling — for local backends (no cross-process events)."""
        deadline = time.time() + timeout
        poll_interval = 0.5  # Check every 500ms

        while time.time() < deadline:
            messages = self.receive_messages(include_room=include_room)
            if messages:
                return messages
            remaining = deadline - time.time()
            if remaining > 0:
                time.sleep(min(poll_interval, remaining))

        return []

    def poll(
        self,
        include_room: bool = True,
    ) -> list[ReceivedMessage]:
        """Poll for new messages (immediate, non-blocking).

        Convenience wrapper around receive_messages.

        Args:
            include_room: Whether to include room messages

        Returns:
            List of received messages
        """
        return self.receive_messages(include_room=include_room)

    def _serialize_with_compression(
        self,
        message: CoordinationMessage,
    ) -> tuple[str, Optional[str]]:
        """Serialize and optionally compress a message.

        Returns:
            Tuple of (body, compression_method)
        """
        serialized = serialize_message(message)
        return compress_payload(serialized)

    def _content_type_with_compression(
        self,
        compression: Optional[str],
    ) -> str:
        """Get content type, adding compression parameter if compressed."""
        if compression:
            return f"{COORDINATION_CONTENT_TYPE}; compression={compression}"
        return COORDINATION_CONTENT_TYPE

    def _parse_message(self, raw: dict[str, Any]) -> Optional[ReceivedMessage]:
        """Parse a raw deaddrop message into a ReceivedMessage.

        Args:
            raw: Raw message dict from deaddrop

        Returns:
            ReceivedMessage or None if not a coordination message
        """
        content_type = raw.get("content_type", "")

        # Check if this is a coordination message
        if not content_type.startswith(COORDINATION_CONTENT_TYPE):
            return None

        body = raw.get("body", "")

        # Check for compression
        compression = None
        if "compression=" in content_type:
            # Parse compression parameter
            for part in content_type.split(";"):
                part = part.strip()
                if part.startswith("compression="):
                    compression = part.split("=", 1)[1]
                    break

        # Decompress if needed
        try:
            decompressed = decompress_payload(body, compression)
            message = deserialize_message(decompressed)
        except (ValueError, json.JSONDecodeError):
            return None

        return ReceivedMessage(
            message=message,
            from_id=raw.get("from") or raw.get("from_id", ""),
            mid=raw.get("mid", ""),
            raw=raw,
        )


def create_coordination_namespace(
    deaddrop: Deaddrop,
    display_name: str = "Coordination Session",
) -> dict[str, Any]:
    """Create a new coordination namespace.

    Args:
        deaddrop: Deaddrop client
        display_name: Human-readable name for the namespace

    Returns:
        Namespace info dict with ns, secret, etc.
    """
    return deaddrop.create_namespace(display_name=display_name)


def create_identity_with_invite(
    deaddrop: Deaddrop,
    namespace_id: str,
    namespace_secret: str,
    display_name: str,
    expires_in: str = "24h",
) -> tuple[dict[str, Any], str]:
    """Create an identity and an invite for it.

    This is the pattern for coordinator to provision agent identities:
    1. Create identity
    2. Create invite for that identity
    3. Pass invite URL to agent
    4. Dispose of identity secret (agent will claim its own)

    Args:
        deaddrop: Deaddrop client
        namespace_id: Namespace ID
        namespace_secret: Namespace secret
        display_name: Display name for the identity
        expires_in: Invite expiration (default 24h)

    Returns:
        Tuple of (identity_info, invite_url)
    """
    # Create identity
    identity = deaddrop.create_identity(
        ns=namespace_id,
        display_name=display_name,
        ns_secret=namespace_secret,
    )

    # Create invite for this identity
    # Note: This requires the deaddrop CLI or API - may need adjustment
    # based on how invites work in the library
    # For now, return a placeholder that will be filled in during integration

    # The invite URL format would be something like:
    # https://deaddrop-server/join/{invite_id}#{key}
    invite_url = f"deaddrop://{namespace_id}/{identity['id']}/invite"

    return identity, invite_url


def create_coordination_room(
    deaddrop: Deaddrop,
    namespace_id: str,
    creator_secret: str,
    display_name: str = "Coordination",
) -> dict[str, Any]:
    """Create a coordination room for broadcasts.

    Args:
        deaddrop: Deaddrop client
        namespace_id: Namespace ID
        creator_secret: Creator's identity secret
        display_name: Room display name

    Returns:
        Room info dict with room_id, etc.
    """
    return deaddrop.create_room(
        ns=namespace_id,
        creator_secret=creator_secret,
        display_name=display_name,
    )
