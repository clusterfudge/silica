"""Tests for coordination client context helper."""

import pytest
from deadrop import Deaddrop

from silica.developer.coordination import (
    CoordinationContext,
    ReceivedMessage,
    create_coordination_namespace,
    create_coordination_room,
    TaskAssign,
    Progress,
    Result,
    Idle,
    COORDINATION_CONTENT_TYPE,
)


@pytest.fixture
def deaddrop():
    """Create an in-memory deaddrop for testing."""
    return Deaddrop.in_memory()


@pytest.fixture
def coordination_setup(deaddrop):
    """Set up a coordination namespace with two identities and a room."""
    # Create namespace
    ns = deaddrop.create_namespace(display_name="Test Coordination")

    # Create coordinator identity
    coordinator = deaddrop.create_identity(
        ns=ns["ns"],
        display_name="Coordinator",
        ns_secret=ns["secret"],
    )

    # Create worker identity
    worker = deaddrop.create_identity(
        ns=ns["ns"],
        display_name="Worker-1",
        ns_secret=ns["secret"],
    )

    # Create coordination room
    room = deaddrop.create_room(
        ns=ns["ns"],
        creator_secret=coordinator["secret"],
        display_name="Coordination Room",
    )

    # Add worker to room
    deaddrop.add_room_member(
        ns=ns["ns"],
        room_id=room["room_id"],
        identity_id=worker["id"],
        secret=coordinator["secret"],
    )

    return {
        "namespace": ns,
        "coordinator": coordinator,
        "worker": worker,
        "room": room,
    }


class TestCoordinationContext:
    """Test CoordinationContext class."""

    def test_create_context(self, deaddrop, coordination_setup):
        """Should create a context with all required info."""
        setup = coordination_setup

        ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["coordinator"]["id"],
            identity_secret=setup["coordinator"]["secret"],
            room_id=setup["room"]["room_id"],
        )

        assert ctx.namespace_id == setup["namespace"]["ns"]
        assert ctx.identity_id == setup["coordinator"]["id"]
        assert ctx.room_id == setup["room"]["room_id"]

    def test_send_message(self, deaddrop, coordination_setup):
        """Should send coordination messages to specific identity."""
        setup = coordination_setup

        # Create coordinator context
        coordinator_ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["coordinator"]["id"],
            identity_secret=setup["coordinator"]["secret"],
            room_id=setup["room"]["room_id"],
        )

        # Send task to worker
        task = TaskAssign(
            task_id="task-123",
            description="Test task",
            context={"key": "value"},
        )
        result = coordinator_ctx.send_message(setup["worker"]["id"], task)

        assert "mid" in result

        # Worker should receive it
        inbox = deaddrop.get_inbox(
            ns=setup["namespace"]["ns"],
            identity_id=setup["worker"]["id"],
            secret=setup["worker"]["secret"],
        )
        assert len(inbox) == 1
        assert COORDINATION_CONTENT_TYPE in inbox[0]["content_type"]

    def test_receive_messages(self, deaddrop, coordination_setup):
        """Should receive and parse coordination messages."""
        setup = coordination_setup

        # Create contexts
        coordinator_ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["coordinator"]["id"],
            identity_secret=setup["coordinator"]["secret"],
            room_id=setup["room"]["room_id"],
        )

        worker_ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["worker"]["id"],
            identity_secret=setup["worker"]["secret"],
            room_id=setup["room"]["room_id"],
            coordinator_id=setup["coordinator"]["id"],
        )

        # Coordinator sends task
        task = TaskAssign(
            task_id="task-456",
            description="Do something",
        )
        coordinator_ctx.send_message(setup["worker"]["id"], task)

        # Worker receives
        messages = worker_ctx.receive_messages(include_room=False)

        assert len(messages) == 1
        assert isinstance(messages[0], ReceivedMessage)
        assert isinstance(messages[0].message, TaskAssign)
        assert messages[0].message.task_id == "task-456"
        assert messages[0].from_id == setup["coordinator"]["id"]
        assert messages[0].is_room_message is False

    def test_broadcast_to_room(self, deaddrop, coordination_setup):
        """Should broadcast messages to coordination room."""
        setup = coordination_setup

        # Create worker context
        worker_ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["worker"]["id"],
            identity_secret=setup["worker"]["secret"],
            room_id=setup["room"]["room_id"],
            coordinator_id=setup["coordinator"]["id"],
        )

        # Broadcast progress
        progress = Progress(
            task_id="task-789",
            agent_id=setup["worker"]["id"],
            progress=0.5,
            message="Halfway done",
        )
        worker_ctx.broadcast(progress)

        # Coordinator should see it in room
        room_messages = deaddrop.get_room_messages(
            ns=setup["namespace"]["ns"],
            room_id=setup["room"]["room_id"],
            secret=setup["coordinator"]["secret"],
        )

        assert len(room_messages) == 1
        assert COORDINATION_CONTENT_TYPE in room_messages[0]["content_type"]

    def test_send_to_coordinator(self, deaddrop, coordination_setup):
        """Workers should be able to send to coordinator via convenience method."""
        setup = coordination_setup

        # Create worker context with coordinator_id
        worker_ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["worker"]["id"],
            identity_secret=setup["worker"]["secret"],
            room_id=setup["room"]["room_id"],
            coordinator_id=setup["coordinator"]["id"],
        )

        # Send result to coordinator
        result = Result(
            task_id="task-999",
            agent_id=setup["worker"]["id"],
            status="complete",
            summary="All done",
        )
        worker_ctx.send_to_coordinator(result)

        # Coordinator should receive it
        coordinator_ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["coordinator"]["id"],
            identity_secret=setup["coordinator"]["secret"],
            room_id=setup["room"]["room_id"],
        )

        messages = coordinator_ctx.receive_messages(include_room=False)

        assert len(messages) == 1
        assert isinstance(messages[0].message, Result)
        assert messages[0].message.status == "complete"

    def test_send_to_coordinator_without_coordinator_id_raises(
        self, deaddrop, coordination_setup
    ):
        """Should raise if coordinator_id not set."""
        setup = coordination_setup

        ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["worker"]["id"],
            identity_secret=setup["worker"]["secret"],
            # No coordinator_id
        )

        with pytest.raises(ValueError, match="coordinator_id not set"):
            ctx.send_to_coordinator(Idle(agent_id="test"))

    def test_broadcast_without_room_raises(self, deaddrop, coordination_setup):
        """Should raise if room_id not set."""
        setup = coordination_setup

        ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["worker"]["id"],
            identity_secret=setup["worker"]["secret"],
            # No room_id
        )

        with pytest.raises(ValueError, match="room_id not set"):
            ctx.broadcast(Idle(agent_id="test"))

    def test_receive_ignores_non_coordination_messages(
        self, deaddrop, coordination_setup
    ):
        """Should ignore messages that aren't coordination protocol."""
        setup = coordination_setup

        # Send a plain text message
        deaddrop.send_message(
            ns=setup["namespace"]["ns"],
            from_secret=setup["coordinator"]["secret"],
            to_id=setup["worker"]["id"],
            body="Just a plain message",
            content_type="text/plain",
        )

        # Worker context should ignore it
        worker_ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["worker"]["id"],
            identity_secret=setup["worker"]["secret"],
        )

        messages = worker_ctx.receive_messages(include_room=False)
        assert len(messages) == 0

    def test_receive_with_compression(self, deaddrop, coordination_setup):
        """Should handle compressed messages."""
        setup = coordination_setup

        # Create coordinator context
        coordinator_ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["coordinator"]["id"],
            identity_secret=setup["coordinator"]["secret"],
        )

        # Send a large task that will be compressed
        large_context = {"data": "x" * 20000}  # Large enough to compress
        task = TaskAssign(
            task_id="task-large",
            description="Large task",
            context=large_context,
        )
        coordinator_ctx.send_message(setup["worker"]["id"], task)

        # Worker receives
        worker_ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["worker"]["id"],
            identity_secret=setup["worker"]["secret"],
        )

        messages = worker_ctx.receive_messages(include_room=False)

        assert len(messages) == 1
        assert isinstance(messages[0].message, TaskAssign)
        assert messages[0].message.context == large_context


class TestCreateCoordinationNamespace:
    """Test namespace creation helper."""

    def test_create_namespace(self, deaddrop):
        """Should create a namespace via deaddrop."""
        ns = create_coordination_namespace(deaddrop, "My Coordination")

        assert "ns" in ns
        assert "secret" in ns


class TestCreateCoordinationRoom:
    """Test room creation helper."""

    def test_create_room(self, deaddrop):
        """Should create a coordination room."""
        ns = deaddrop.create_namespace(display_name="Test")
        identity = deaddrop.create_identity(
            ns=ns["ns"],
            display_name="Coord",
            ns_secret=ns["secret"],
        )

        room = create_coordination_room(
            deaddrop,
            ns["ns"],
            identity["secret"],
            "Test Room",
        )

        assert "room_id" in room


class TestPolling:
    """Test polling functionality."""

    def test_poll_incremental(self, deaddrop, coordination_setup):
        """Should only return new messages on subsequent polls."""
        setup = coordination_setup

        coordinator_ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["coordinator"]["id"],
            identity_secret=setup["coordinator"]["secret"],
        )

        worker_ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=setup["namespace"]["ns"],
            namespace_secret=setup["namespace"]["secret"],
            identity_id=setup["worker"]["id"],
            identity_secret=setup["worker"]["secret"],
        )

        # Send first message
        coordinator_ctx.send_message(
            setup["worker"]["id"],
            TaskAssign(task_id="task-1", description="First"),
        )

        # First poll
        messages1 = worker_ctx.poll(wait=0, include_room=False)
        assert len(messages1) == 1
        assert messages1[0].message.task_id == "task-1"

        # Send second message
        coordinator_ctx.send_message(
            setup["worker"]["id"],
            TaskAssign(task_id="task-2", description="Second"),
        )

        # Second poll should only get the new message
        messages2 = worker_ctx.poll(wait=0, include_room=False)
        assert len(messages2) == 1
        assert messages2[0].message.task_id == "task-2"

        # Third poll should be empty
        messages3 = worker_ctx.poll(wait=0, include_room=False)
        assert len(messages3) == 0
