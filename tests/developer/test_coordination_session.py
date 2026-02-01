"""Tests for coordination session management."""

import pytest
from unittest.mock import patch

from deadrop import Deaddrop

from silica.developer.coordination.session import (
    AgentState,
    AgentInfo,
    HumanParticipant,
    SessionState,
    CoordinationSession,
    get_session_file,
    list_sessions,
    delete_session,
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


class TestAgentInfo:
    """Test AgentInfo dataclass."""

    def test_create_agent_info(self):
        info = AgentInfo(
            agent_id="agent-1",
            identity_id="id-123",
            display_name="Worker 1",
            workspace_name="worker-1-myproject",
        )
        assert info.state == AgentState.SPAWNING
        assert info.current_task_id is None
        assert info.created_at is not None

    def test_roundtrip(self):
        original = AgentInfo(
            agent_id="agent-2",
            identity_id="id-456",
            display_name="Worker 2",
            workspace_name="worker-2-myproject",
            state=AgentState.WORKING,
            current_task_id="task-123",
        )
        data = original.to_dict()
        restored = AgentInfo.from_dict(data)

        assert restored.agent_id == original.agent_id
        assert restored.state == original.state
        assert restored.current_task_id == original.current_task_id


class TestSessionState:
    """Test SessionState dataclass."""

    def test_create_session_state(self):
        state = SessionState(
            session_id="sess-123",
            namespace_id="ns-456",
            namespace_secret="secret",
            coordinator_id="coord-789",
            coordinator_secret="coord-secret",
            room_id="room-abc",
        )
        assert state.display_name == "Coordination Session"
        assert len(state.agents) == 0

    def test_roundtrip_with_agents(self):
        agent = AgentInfo(
            agent_id="agent-1",
            identity_id="id-123",
            display_name="Worker",
            workspace_name="workspace",
            state=AgentState.IDLE,
        )
        human = HumanParticipant(
            identity_id="human-id",
            display_name="Sean",
        )

        original = SessionState(
            session_id="sess-123",
            namespace_id="ns-456",
            namespace_secret="secret",
            coordinator_id="coord-789",
            coordinator_secret="coord-secret",
            room_id="room-abc",
            agents={"agent-1": agent},
            humans={"human-id": human},
        )

        data = original.to_dict()
        restored = SessionState.from_dict(data)

        assert restored.session_id == original.session_id
        assert "agent-1" in restored.agents
        assert restored.agents["agent-1"].state == AgentState.IDLE
        assert "human-id" in restored.humans
        assert restored.humans["human-id"].display_name == "Sean"


class TestCoordinationSession:
    """Test CoordinationSession class."""

    def test_create_session(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(
            deaddrop,
            display_name="Test Session",
        )

        assert session.session_id is not None
        assert session.namespace_id is not None
        assert session.context is not None

        # Verify state file was created
        session_file = temp_sessions_dir / f"{session.session_id}.json"
        assert session_file.exists()

    def test_resume_session_by_id(self, deaddrop, temp_sessions_dir):
        # Create session
        original = CoordinationSession.create_session(deaddrop, "Original Session")
        session_id = original.session_id

        # Register an agent
        original.register_agent(
            agent_id="agent-1",
            identity_id="id-123",
            display_name="Worker",
            workspace_name="workspace",
        )

        # Resume
        resumed = CoordinationSession.resume_session(
            deaddrop,
            session_id=session_id,
        )

        assert resumed.session_id == session_id
        assert resumed.state.display_name == "Original Session"
        assert "agent-1" in resumed.state.agents

    def test_resume_nonexistent_session_raises(self, deaddrop, temp_sessions_dir):
        with pytest.raises(FileNotFoundError):
            CoordinationSession.resume_session(
                deaddrop,
                session_id="nonexistent",
            )

    def test_resume_without_args_raises(self, deaddrop):
        with pytest.raises(ValueError, match="Either session_id or namespace_secret"):
            CoordinationSession.resume_session(deaddrop)

    def test_get_state(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)
        state = session.get_state()

        assert "session_id" in state
        assert "namespace_id" in state
        assert "agents" in state
        assert isinstance(state["agents"], dict)


class TestAgentRegistry:
    """Test agent registry operations."""

    def test_register_agent(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)

        agent = session.register_agent(
            agent_id="agent-1",
            identity_id="id-123",
            display_name="Worker 1",
            workspace_name="worker-1-proj",
        )

        assert agent.agent_id == "agent-1"
        assert agent.state == AgentState.SPAWNING
        assert "agent-1" in session.state.agents

    def test_update_agent_state(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)
        session.register_agent(
            agent_id="agent-1",
            identity_id="id-123",
            display_name="Worker",
            workspace_name="workspace",
        )

        # Update to WORKING
        agent = session.update_agent_state(
            "agent-1",
            AgentState.WORKING,
            task_id="task-456",
        )
        assert agent.state == AgentState.WORKING
        assert agent.current_task_id == "task-456"
        assert agent.last_seen is not None

        # Update to IDLE clears task
        agent = session.update_agent_state("agent-1", AgentState.IDLE)
        assert agent.state == AgentState.IDLE
        assert agent.current_task_id is None

    def test_update_nonexistent_agent_raises(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)
        with pytest.raises(KeyError):
            session.update_agent_state("nonexistent", AgentState.IDLE)

    def test_get_agent(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)
        session.register_agent(
            agent_id="agent-1",
            identity_id="id-123",
            display_name="Worker",
            workspace_name="workspace",
        )

        agent = session.get_agent("agent-1")
        assert agent is not None
        assert agent.display_name == "Worker"

        assert session.get_agent("nonexistent") is None

    def test_get_agent_by_identity(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)
        session.register_agent(
            agent_id="agent-1",
            identity_id="id-123",
            display_name="Worker",
            workspace_name="workspace",
        )

        agent = session.get_agent_by_identity("id-123")
        assert agent is not None
        assert agent.agent_id == "agent-1"

        assert session.get_agent_by_identity("nonexistent") is None

    def test_list_agents(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)
        session.register_agent("a1", "id1", "W1", "ws1")
        session.register_agent("a2", "id2", "W2", "ws2")

        all_agents = session.list_agents()
        assert len(all_agents) == 2

        # Filter by state
        session.update_agent_state("a1", AgentState.IDLE)
        idle_agents = session.list_agents(state_filter=AgentState.IDLE)
        assert len(idle_agents) == 1
        assert idle_agents[0].agent_id == "a1"

    def test_remove_agent(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)
        session.register_agent("agent-1", "id-123", "Worker", "workspace")

        removed = session.remove_agent("agent-1")
        assert removed is not None
        assert removed.agent_id == "agent-1"
        assert "agent-1" not in session.state.agents

        # Remove nonexistent returns None
        assert session.remove_agent("nonexistent") is None


class TestHumanParticipants:
    """Test human participant operations."""

    def test_register_human(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)

        human = session.register_human(
            identity_id="human-123",
            display_name="Sean",
        )

        assert human.identity_id == "human-123"
        assert human.display_name == "Sean"
        assert "human-123" in session.state.humans

    def test_list_humans(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)
        session.register_human("h1", "Human 1")
        session.register_human("h2", "Human 2")

        humans = session.list_humans()
        assert len(humans) == 2


class TestRoomManagement:
    """Test room membership operations."""

    def test_add_agent_to_room(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)

        # Create a real identity for the agent
        identity = deaddrop.create_identity(
            ns=session.namespace_id,
            display_name="Worker",
            ns_secret=session.namespace_secret,
        )

        session.register_agent(
            agent_id="agent-1",
            identity_id=identity["id"],
            display_name="Worker",
            workspace_name="workspace",
        )

        result = session.add_agent_to_room("agent-1")
        assert result is True

    def test_add_nonexistent_agent_to_room_fails(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)
        result = session.add_agent_to_room("nonexistent")
        assert result is False


class TestSessionUtilities:
    """Test session utility functions."""

    def test_list_sessions(self, deaddrop, temp_sessions_dir):
        # Create multiple sessions
        s1 = CoordinationSession.create_session(deaddrop, "Session 1")
        s2 = CoordinationSession.create_session(deaddrop, "Session 2")

        sessions = list_sessions()
        assert len(sessions) >= 2

        session_ids = [s["session_id"] for s in sessions]
        assert s1.session_id in session_ids
        assert s2.session_id in session_ids

    def test_delete_session(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)
        session_id = session.session_id

        # Verify file exists
        assert get_session_file(session_id).exists()

        # Delete
        result = delete_session(session_id)
        assert result is True
        assert not get_session_file(session_id).exists()

        # Delete nonexistent returns False
        assert delete_session("nonexistent") is False


class TestStatePersistence:
    """Test that state changes are persisted."""

    def test_agent_changes_persisted(self, deaddrop, temp_sessions_dir):
        session = CoordinationSession.create_session(deaddrop)
        session.register_agent("a1", "id1", "W1", "ws1")

        # Reload from disk
        reloaded = CoordinationSession.resume_session(
            deaddrop,
            session_id=session.session_id,
        )
        assert "a1" in reloaded.state.agents

        # Update state
        session.update_agent_state("a1", AgentState.WORKING, task_id="task-1")

        # Reload again
        reloaded2 = CoordinationSession.resume_session(
            deaddrop,
            session_id=session.session_id,
        )
        assert reloaded2.state.agents["a1"].state == AgentState.WORKING
        assert reloaded2.state.agents["a1"].current_task_id == "task-1"
