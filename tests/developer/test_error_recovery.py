"""Tests for error recovery in coordination module."""

import json
import pytest
from unittest.mock import patch
from silica.developer.coordination.client import (
    CoordinationContext,
    with_retry,
    DeaddropConnectionError,
)
from silica.developer.coordination import Idle, Progress


class TestWithRetry:
    """Test the retry decorator."""

    def test_succeeds_first_attempt(self):
        """Function that succeeds on first attempt should work."""
        call_count = 0

        @with_retry(max_attempts=3, base_delay=0.01)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_func()
        assert result == "success"
        assert call_count == 1

    def test_succeeds_after_retry(self):
        """Function that fails then succeeds should retry."""
        call_count = 0

        @with_retry(max_attempts=3, base_delay=0.01)
        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("Network error")
            return "success"

        result = flaky_func()
        assert result == "success"
        assert call_count == 2

    def test_fails_after_max_attempts(self):
        """Function that always fails should raise after max attempts."""
        call_count = 0

        @with_retry(max_attempts=3, base_delay=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Network error")

        with pytest.raises(DeaddropConnectionError) as exc_info:
            always_fails()

        assert "failed after 3 attempts" in str(exc_info.value)
        assert call_count == 3

    def test_custom_max_attempts(self):
        """Custom max_attempts should be respected."""
        call_count = 0

        @with_retry(max_attempts=5, base_delay=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Network error")

        with pytest.raises(DeaddropConnectionError):
            always_fails()

        assert call_count == 5

    def test_exponential_backoff(self):
        """Delays should increase exponentially."""
        delays = []

        def mock_sleep(seconds):
            delays.append(seconds)

        with patch("silica.developer.coordination.client.time.sleep", mock_sleep):

            @with_retry(max_attempts=4, base_delay=1.0, jitter=False)
            def always_fails():
                raise ConnectionError("Network error")

            with pytest.raises(DeaddropConnectionError):
                always_fails()

        # 3 sleeps for 4 attempts (no sleep before first or after last)
        assert len(delays) == 3
        # Each delay should be approximately doubled (1, 2, 4)
        assert delays[0] == pytest.approx(1.0, rel=0.1)
        assert delays[1] == pytest.approx(2.0, rel=0.1)
        assert delays[2] == pytest.approx(4.0, rel=0.1)


class TestSendMessageRetry:
    """Test retry behavior for send_message."""

    def test_send_message_retries_on_failure(self, deaddrop, coordination_setup):
        """send_message should retry on connection failure."""
        session, context = coordination_setup

        # Create recipient
        recipient = deaddrop.create_identity(
            ns=session.namespace_id,
            display_name="Recipient",
            ns_secret=session.namespace_secret,
        )

        # Mock send_message to fail twice then succeed
        original_send = deaddrop.send_message
        call_count = 0

        def flaky_send(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Simulated network failure")
            return original_send(*args, **kwargs)

        with patch.object(deaddrop, "send_message", flaky_send):
            # Should succeed after retries
            result = context.send_message(
                recipient["id"], Idle(agent_id="test"), retry=True
            )
            assert result is not None
            assert call_count == 3

    def test_send_message_no_retry(self, deaddrop, coordination_setup):
        """send_message with retry=False should not retry."""
        session, context = coordination_setup

        recipient = deaddrop.create_identity(
            ns=session.namespace_id,
            display_name="Recipient",
            ns_secret=session.namespace_secret,
        )

        call_count = 0

        def always_fails(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Simulated network failure")

        with patch.object(deaddrop, "send_message", always_fails):
            with pytest.raises(ConnectionError):
                context.send_message(
                    recipient["id"], Idle(agent_id="test"), retry=False
                )
            # Should only try once
            assert call_count == 1


class TestReceiveMessagesErrorHandling:
    """Test error handling for receive_messages."""

    def test_receive_skips_unparseable_messages(self, deaddrop, coordination_setup):
        """Messages that fail to parse should be skipped."""
        session, context = coordination_setup

        # Send a valid message
        context.broadcast(Idle(agent_id="test"))

        # Mock _parse_message to fail for first message
        original_parse = context._parse_message
        call_count = 0

        def flaky_parse(raw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Parse error")
            return original_parse(raw)

        with patch.object(context, "_parse_message", flaky_parse):
            # Should not raise, just skip the bad message
            messages = context.receive_messages(include_room=True, retry=False)
            # Message was skipped due to simulated error
            assert len(messages) == 0

    def test_receive_continues_after_inbox_failure(self, deaddrop, coordination_setup):
        """If inbox fails, should still try room."""
        session, context = coordination_setup

        # Send a room message
        context.broadcast(Progress(task_id="t1", message="Working"))

        # Mock get_inbox to fail
        def fail_inbox(*args, **kwargs):
            raise ConnectionError("Inbox unavailable")

        with patch.object(deaddrop, "get_inbox", fail_inbox):
            # Should still get room messages - main point: doesn't crash
            context.receive_messages(include_room=True, retry=True)


class TestMessageParseErrors:
    """Test that message parse errors are handled gracefully."""

    def test_invalid_json_skipped(self, deaddrop, coordination_setup):
        """Invalid JSON messages should be skipped."""
        session, context = coordination_setup

        # Send a raw message with invalid content
        deaddrop.send_room_message(
            ns=session.namespace_id,
            room_id=context.room_id,
            secret=context.identity_secret,
            body="not valid json {{{",
            content_type="application/vnd.silica.coordination+json",
        )

        # Should not raise
        messages = context.receive_messages(include_room=True)
        # Invalid message should be skipped
        assert len(messages) == 0

    def test_unknown_message_type_skipped(self, deaddrop, coordination_setup):
        """Messages with unknown types should be skipped."""
        session, context = coordination_setup

        # Send a message with unknown type
        deaddrop.send_room_message(
            ns=session.namespace_id,
            room_id=context.room_id,
            secret=context.identity_secret,
            body=json.dumps({"type": "unknown_type", "data": "test"}),
            content_type="application/vnd.silica.coordination+json",
        )

        # Should not raise
        messages = context.receive_messages(include_room=True)
        # Unknown type should be skipped
        assert len(messages) == 0


# Fixtures


@pytest.fixture
def deaddrop():
    """Create an in-memory deaddrop client."""
    from deadrop import Deaddrop

    return Deaddrop.in_memory()


@pytest.fixture
def coordination_setup(deaddrop):
    """Set up a basic coordination session and context."""
    # Create namespace
    ns = deaddrop.create_namespace(display_name="Test")

    # Create coordinator identity
    coordinator = deaddrop.create_identity(
        ns=ns["ns"], display_name="Coordinator", ns_secret=ns["secret"]
    )

    # Create room
    room = deaddrop.create_room(
        ns=ns["ns"], creator_secret=coordinator["secret"], display_name="Coordination"
    )

    # Create context
    context = CoordinationContext(
        deaddrop=deaddrop,
        namespace_id=ns["ns"],
        namespace_secret=ns["secret"],
        identity_id=coordinator["id"],
        identity_secret=coordinator["secret"],
        room_id=room["room_id"],
    )

    # Return a simple object with session-like properties
    class MockSession:
        pass

    session = MockSession()
    session.namespace_id = ns["ns"]
    session.namespace_secret = ns["secret"]
    session.deaddrop = deaddrop

    return session, context
