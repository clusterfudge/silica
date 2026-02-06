"""Tests for coordinator tools."""

import pytest
from unittest.mock import patch

from deadrop import Deaddrop

from silica.developer.coordination.session import (
    CoordinationSession,
    AgentState,
)
from silica.developer.tools.coordination import (
    set_current_session,
    get_current_session,
    message_agent,
    broadcast,
    poll_messages,
    list_agents,
    get_session_state,
    create_human_invite,
    grant_permission,
    escalate_to_user,
    check_agent_health,
)


@pytest.fixture
def deaddrop():
    """Create an in-memory deaddrop for testing."""
    return Deaddrop.in_memory()


@pytest.fixture
def temp_sessions_dir(tmp_path):
    """Use a temporary directory for session storage."""
    sessions_dir = tmp_path / "coordination"
    sessions_dir.mkdir()
    with patch(
        "silica.developer.coordination.session.get_sessions_dir",
        return_value=sessions_dir,
    ):
        yield sessions_dir


@pytest.fixture
def session(deaddrop, temp_sessions_dir):
    """Create a coordination session and set it as current."""
    session = CoordinationSession.create_session(deaddrop, "Test Session")
    set_current_session(session)
    yield session
    set_current_session(None)


@pytest.fixture
def session_with_agent(session, deaddrop):
    """Create a session with a registered agent."""
    # Create a real identity for the agent
    identity = deaddrop.create_identity(
        ns=session.namespace_id,
        display_name="Worker-1",
        ns_secret=session.namespace_secret,
    )

    # Register agent
    session.register_agent(
        agent_id="agent-1",
        identity_id=identity["id"],
        display_name="Worker-1",
        workspace_name="worker-1-project",
    )

    # Add to room
    session.add_agent_to_room("agent-1")

    # Update to IDLE so it's ready for tasks
    session.update_agent_state("agent-1", AgentState.IDLE)

    return session, identity


class TestSessionManagement:
    """Test session management functions."""

    def test_get_current_session_raises_when_none(self, temp_sessions_dir):
        """Should raise when no session is active."""
        set_current_session(None)
        with pytest.raises(RuntimeError, match="No coordination session active"):
            get_current_session()

    def test_set_and_get_session(self, session):
        """Should be able to set and get session."""
        current = get_current_session()
        assert current.session_id == session.session_id


class TestMessageAgent:
    """Test message_agent tool."""

    def test_message_nonexistent_agent(self, session):
        result = message_agent("nonexistent", "task", task_id="t1", description="Test")
        assert "not found" in result

    def test_send_task_message(self, session_with_agent):
        session, identity = session_with_agent

        result = message_agent(
            "agent-1",
            "task",
            task_id="task-123",
            description="Do something useful",
            context={"key": "value"},
        )

        assert "✓" in result
        assert "Worker-1" in result

        # Agent should be in WORKING state
        agent = session.get_agent("agent-1")
        assert agent.state == AgentState.WORKING
        assert agent.current_task_id == "task-123"

    def test_send_terminate_message(self, session_with_agent):
        session, identity = session_with_agent

        result = message_agent(
            "agent-1",
            "terminate",
            reason="Task complete",
        )

        assert "✓" in result
        assert "terminate" in result

        # Agent should be TERMINATED
        agent = session.get_agent("agent-1")
        assert agent.state == AgentState.TERMINATED

    def test_unknown_message_type(self, session_with_agent):
        result = message_agent("agent-1", "unknown_type")
        assert "❌" in result
        assert "Unknown message type" in result


class TestBroadcast:
    """Test broadcast tool."""

    def test_broadcast_message(self, session):
        result = broadcast("Hello everyone!", task_id="task-1")
        assert "✓" in result
        assert "Broadcast" in result


class TestPollMessages:
    """Test poll_messages tool."""

    def test_poll_no_messages(self, session):
        result = poll_messages(wait=0)
        assert "No new messages" in result

    def test_poll_receives_message(self, session_with_agent, deaddrop):
        session, identity = session_with_agent

        # Simulate agent sending a message to coordinator
        from silica.developer.coordination import Progress

        progress = Progress(
            task_id="task-1",
            agent_id="agent-1",
            progress=0.5,
            message="Halfway done",
        )
        from silica.developer.coordination.client import CoordinationContext

        agent_ctx = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=session.namespace_id,
            namespace_secret=session.namespace_secret,
            identity_id=identity["id"],
            identity_secret=identity["secret"],
            coordinator_id=session.state.coordinator_id,
        )
        agent_ctx.send_to_coordinator(progress)

        # Poll should receive it
        result = poll_messages(wait=0)

        assert "1 new message" in result
        assert "Worker-1" in result
        assert "progress" in result
        assert "50%" in result


class TestListAgents:
    """Test list_agents tool."""

    def test_list_no_agents(self, session):
        result = list_agents()
        assert "No agents" in result

    def test_list_agents(self, session_with_agent):
        session, _ = session_with_agent

        result = list_agents()
        assert "1 agent" in result
        assert "Worker-1" in result
        assert "agent-1" in result

    def test_list_agents_with_filter(self, session_with_agent):
        session, _ = session_with_agent

        # Agent is IDLE
        result = list_agents(state_filter="idle")
        assert "Worker-1" in result

        result = list_agents(state_filter="working")
        assert "No agents" in result

    def test_list_agents_invalid_filter(self, session):
        result = list_agents(state_filter="invalid")
        assert "Invalid state filter" in result

    def test_list_agents_with_details(self, session_with_agent):
        session, _ = session_with_agent

        result = list_agents(show_details=True)
        assert "Workspace:" in result
        assert "worker-1-project" in result


class TestGetSessionState:
    """Test get_session_state tool."""

    def test_get_session_state(self, session_with_agent):
        session, _ = session_with_agent

        result = get_session_state()

        assert "Session:" in result
        assert session.session_id in result
        assert "Test Session" in result
        assert "Agents:** 1" in result  # Markdown formatting


class TestCreateHumanInvite:
    """Test create_human_invite tool."""

    def test_create_human_invite(self, session):
        result = create_human_invite("Sean")

        assert "Human Invite Created" in result
        assert "Sean" in result
        assert "Namespace:" in result
        assert session.namespace_id in result

        # Human should be registered
        humans = session.list_humans()
        assert len(humans) == 1
        assert humans[0].display_name == "Sean"


class TestGrantPermission:
    """Test grant_permission tool."""

    def test_grant_permission_allow(self, session_with_agent):
        session, _ = session_with_agent

        # Set agent to waiting for permission
        session.update_agent_state("agent-1", AgentState.WAITING_PERMISSION)

        result = grant_permission(
            "perm-123",
            "allow",
            agent_id="agent-1",
            reason="Approved",
        )

        assert "✓" in result
        assert "allow" in result

        # Agent should be back to WORKING
        agent = session.get_agent("agent-1")
        assert agent.state == AgentState.WORKING

    def test_grant_permission_deny(self, session_with_agent):
        result = grant_permission(
            "perm-456",
            "deny",
            agent_id="agent-1",
            reason="Too risky",
        )

        assert "✓" in result
        assert "deny" in result

    def test_grant_permission_invalid_decision(self, session_with_agent):
        result = grant_permission("agent-1-perm-789", "maybe")
        assert "Invalid decision" in result

    def test_grant_permission_unknown_agent(self, session):
        result = grant_permission("unknown-perm-123", "allow")
        assert "Cannot determine agent" in result


class TestEscalateToUser:
    """Test escalate_to_user tool."""

    def test_escalate_no_humans(self, session):
        result = escalate_to_user("perm-123", "Agent wants to run rm -rf /")
        assert "No human participants" in result
        assert "queued" in result

    def test_escalate_to_human(self, session):
        # Add a human first
        create_human_invite("Sean")

        result = escalate_to_user("perm-456", "Agent wants to access /etc/passwd")
        assert "✓" in result
        assert "1 human" in result


class TestSpawnAgent:
    """Test spawn_agent tool."""

    def test_spawn_agent_basic(self, session):
        from silica.developer.tools.coordination import spawn_agent

        result = spawn_agent(workspace_name="test-worker")

        assert "Agent Created" in result
        assert "test-worker" in result
        assert "DEADDROP_INVITE_URL" in result
        assert "COORDINATION_AGENT_ID" in result

        # Agent should be registered
        agents = session.list_agents()
        assert len(agents) == 1
        assert agents[0].workspace_name == "test-worker"
        assert agents[0].state == AgentState.SPAWNING

    def test_spawn_agent_auto_names(self, session):
        from silica.developer.tools.coordination import spawn_agent

        result = spawn_agent()

        assert "Agent Created" in result
        # Should have generated names
        assert "worker-" in result.lower()

    def test_spawn_agent_with_display_name(self, session):
        from silica.developer.tools.coordination import spawn_agent

        result = spawn_agent(
            workspace_name="research-agent",
            display_name="Research Bot",
        )

        assert "Research Bot" in result

        agents = session.list_agents()
        assert agents[0].display_name == "Research Bot"

    def test_spawn_multiple_agents(self, session):
        from silica.developer.tools.coordination import spawn_agent

        spawn_agent(workspace_name="worker-1", display_name="Worker 1")
        spawn_agent(workspace_name="worker-2", display_name="Worker 2")

        agents = session.list_agents()
        assert len(agents) == 2


class TestTerminateAgent:
    """Test terminate_agent tool."""

    def test_terminate_agent(self, session_with_agent):
        from silica.developer.tools.coordination import terminate_agent

        session, _ = session_with_agent

        result = terminate_agent("agent-1", reason="Job done")

        assert "✓" in result
        assert "Terminated" in result
        assert "Worker-1" in result
        assert "silica remote destroy" in result

        # Agent should be TERMINATED
        agent = session.get_agent("agent-1")
        assert agent.state == AgentState.TERMINATED

    def test_terminate_nonexistent_agent(self, session):
        from silica.developer.tools.coordination import terminate_agent

        result = terminate_agent("nonexistent")
        assert "not found" in result


class TestListPendingPermissions:
    """Test the list_pending_permissions tool."""

    def test_list_no_pending(self, session):
        """Should handle empty queue."""
        from silica.developer.tools.coordination import list_pending_permissions

        result = list_pending_permissions()
        assert "No pending permissions" in result

    def test_list_pending_permissions(self, session):
        """Should list pending permissions."""
        from silica.developer.tools.coordination import list_pending_permissions

        # Queue some permissions
        session.queue_permission("req-1", "agent-1", "shell", "rm -rf /tmp", "cleaning")
        session.queue_permission(
            "req-2", "agent-2", "read_file", "/etc/passwd", "reading"
        )

        result = list_pending_permissions()
        assert "req-1" in result
        assert "req-2" in result
        assert "shell" in result
        assert "read_file" in result

    def test_list_with_filter(self, session):
        """Should filter by agent or status."""
        from silica.developer.tools.coordination import list_pending_permissions

        session.queue_permission("req-1", "agent-1", "shell", "cmd1", "ctx1")
        session.queue_permission("req-2", "agent-2", "shell", "cmd2", "ctx2")

        result = list_pending_permissions(agent_id="agent-1")
        assert "req-1" in result
        assert "req-2" not in result


class TestGrantQueuedPermission:
    """Test the grant_queued_permission tool."""

    def test_grant_permission(self, session_with_agent):
        """Should grant a queued permission."""
        from silica.developer.tools.coordination import grant_queued_permission

        session, identity = session_with_agent

        # Queue a permission for existing agent
        session.queue_permission("req-1", "agent-1", "shell", "cmd", "ctx")

        result = grant_queued_permission("req-1", "allow")
        assert "granted" in result.lower()

        # Check status updated
        pending = session.get_pending_permission("req-1")
        assert pending.status == "granted"

    def test_deny_permission(self, session_with_agent):
        """Should deny a queued permission."""
        from silica.developer.tools.coordination import grant_queued_permission

        session, identity = session_with_agent

        session.queue_permission("req-1", "agent-1", "shell", "rm -rf /", "dangerous")

        result = grant_queued_permission("req-1", "deny", reason="Too dangerous")
        assert "denied" in result.lower()

        pending = session.get_pending_permission("req-1")
        assert pending.status == "denied"

    def test_grant_nonexistent(self, session):
        """Should handle nonexistent request."""
        from silica.developer.tools.coordination import grant_queued_permission

        result = grant_queued_permission("req-999", "allow")
        assert "not found" in result.lower()


class TestClearExpiredPermissions:
    """Test the clear_expired_permissions tool."""

    def test_clear_no_expired(self, session):
        """Should handle no expired permissions."""
        from silica.developer.tools.coordination import clear_expired_permissions

        result = clear_expired_permissions()
        assert "No expired" in result

    def test_clear_expired(self, session):
        """Should clear old permissions."""
        from silica.developer.tools.coordination import clear_expired_permissions
        from silica.developer.coordination.session import PendingPermission

        # Manually add an old permission
        from datetime import datetime, timedelta

        old_time = (datetime.utcnow() - timedelta(hours=48)).isoformat()
        old_perm = PendingPermission(
            request_id="old-req",
            agent_id="agent-1",
            action="shell",
            resource="cmd",
            context="ctx",
            requested_at=old_time,
        )
        session.state.pending_permissions["old-req"] = old_perm
        session.save_state()

        result = clear_expired_permissions(max_age_hours=24)
        assert "1" in result

        # Check status
        pending = session.get_pending_permission("old-req")
        assert pending.status == "expired"


class TestCheckAgentHealth:
    """Test check_agent_health tool."""

    def test_check_health_no_agents(self, session):
        result = check_agent_health()
        assert "No agents" in result

    def test_check_health_healthy_agent(self, session_with_agent):
        session, _ = session_with_agent

        # Update last_seen to now
        session.update_agent_last_seen("agent-1")

        result = check_agent_health()
        assert "Health Report" in result
        assert "healthy" in result.lower()

    def test_check_health_stale_agent(self, session_with_agent):
        from datetime import datetime, timedelta

        session, _ = session_with_agent

        # Set last_seen to 30 minutes ago
        old_time = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
        session.state.agents["agent-1"].last_seen = old_time
        session.save_state()

        result = check_agent_health(stale_minutes=10)
        assert "stale" in result.lower()
