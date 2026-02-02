"""Coordination session management.

Manages the lifecycle of a coordination session including:
- Namespace and identity creation
- Coordination room setup
- Agent registry tracking
- State persistence for resumption
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import json

from deadrop import Deaddrop

from .client import (
    CoordinationContext,
    create_coordination_namespace,
    create_coordination_room,
)


class AgentState(str, Enum):
    """Possible states for a coordinated agent."""

    SPAWNING = "spawning"  # Workspace being created
    STARTING = "starting"  # Agent process starting, connecting to deaddrop
    IDLE = "idle"  # Connected, waiting for task
    WORKING = "working"  # Executing a task
    WAITING_PERMISSION = "waiting_permission"  # Blocked on permission request
    TERMINATED = "terminated"  # Agent shut down


@dataclass
class AgentInfo:
    """Information about a coordinated agent."""

    agent_id: str
    identity_id: str
    display_name: str
    workspace_name: str
    state: AgentState = AgentState.SPAWNING
    current_task_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_seen: Optional[str] = None
    created_by: str = "coordinator"  # Track creator for cleanup
    tmux_session: Optional[str] = None  # For local workers, the tmux session name

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentInfo":
        data = data.copy()
        data["state"] = AgentState(data["state"])
        return cls(**data)


@dataclass
class HumanParticipant:
    """Information about a human participant."""

    identity_id: str
    display_name: str
    joined_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HumanParticipant":
        return cls(**data)


@dataclass
class PendingPermission:
    """A permission request that timed out waiting for response.

    When a worker times out waiting for permission, the request is queued
    so the coordinator can later review and potentially grant it.
    """

    request_id: str
    agent_id: str
    action: str
    resource: str
    context: str
    requested_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    status: str = "pending"  # pending, granted, denied, expired

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PendingPermission":
        return cls(**data)


@dataclass
class SessionState:
    """Serializable state of a coordination session."""

    session_id: str
    namespace_id: str
    namespace_secret: str
    coordinator_id: str
    coordinator_secret: str
    room_id: str
    agents: dict[str, AgentInfo] = field(default_factory=dict)
    humans: dict[str, HumanParticipant] = field(default_factory=dict)
    pending_permissions: dict[str, PendingPermission] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    display_name: str = "Coordination Session"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "namespace_id": self.namespace_id,
            "namespace_secret": self.namespace_secret,
            "coordinator_id": self.coordinator_id,
            "coordinator_secret": self.coordinator_secret,
            "room_id": self.room_id,
            "agents": {k: v.to_dict() for k, v in self.agents.items()},
            "humans": {k: v.to_dict() for k, v in self.humans.items()},
            "pending_permissions": {
                k: v.to_dict() for k, v in self.pending_permissions.items()
            },
            "created_at": self.created_at,
            "display_name": self.display_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        data = data.copy()
        data["agents"] = {
            k: AgentInfo.from_dict(v) for k, v in data.get("agents", {}).items()
        }
        data["humans"] = {
            k: HumanParticipant.from_dict(v) for k, v in data.get("humans", {}).items()
        }
        data["pending_permissions"] = {
            k: PendingPermission.from_dict(v)
            for k, v in data.get("pending_permissions", {}).items()
        }
        return cls(**data)


def get_sessions_dir() -> Path:
    """Get the directory for storing coordination sessions."""
    sessions_dir = Path.home() / ".silica" / "coordination"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def get_session_file(session_id: str) -> Path:
    """Get the file path for a session's state."""
    return get_sessions_dir() / f"{session_id}.json"


class CoordinationSession:
    """Manages a coordination session.

    A session encapsulates:
    - A deaddrop namespace for communication
    - A coordinator identity
    - A coordination room for broadcasts
    - A registry of spawned agents
    - Human participants
    """

    def __init__(
        self,
        deaddrop: Deaddrop,
        state: SessionState,
    ):
        """Initialize with existing state.

        Use create_session() or resume_session() to construct.
        """
        self.deaddrop = deaddrop
        self.state = state

        # Create coordination context for the coordinator
        self._context = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=state.namespace_id,
            namespace_secret=state.namespace_secret,
            identity_id=state.coordinator_id,
            identity_secret=state.coordinator_secret,
            room_id=state.room_id,
        )

    @property
    def session_id(self) -> str:
        return self.state.session_id

    @property
    def namespace_id(self) -> str:
        return self.state.namespace_id

    @property
    def namespace_secret(self) -> str:
        return self.state.namespace_secret

    @property
    def context(self) -> CoordinationContext:
        """Get the coordinator's communication context."""
        return self._context

    @classmethod
    def create_session(
        cls,
        deaddrop: Deaddrop,
        display_name: str = "Coordination Session",
    ) -> "CoordinationSession":
        """Create a new coordination session.

        This creates:
        - A new deaddrop namespace
        - A coordinator identity
        - A coordination room

        Args:
            deaddrop: Deaddrop client
            display_name: Human-readable session name

        Returns:
            New CoordinationSession instance
        """
        # Create namespace
        ns = create_coordination_namespace(deaddrop, display_name)

        # Create coordinator identity
        coordinator = deaddrop.create_identity(
            ns=ns["ns"],
            display_name="Coordinator",
            ns_secret=ns["secret"],
        )

        # Create coordination room
        room = create_coordination_room(
            deaddrop,
            ns["ns"],
            coordinator["secret"],
            "Coordination",
        )

        # Build state
        state = SessionState(
            session_id=ns["ns"][:8],  # Use first 8 chars of namespace as session ID
            namespace_id=ns["ns"],
            namespace_secret=ns["secret"],
            coordinator_id=coordinator["id"],
            coordinator_secret=coordinator["secret"],
            room_id=room["room_id"],
            display_name=display_name,
        )

        session = cls(deaddrop, state)

        # Persist state
        session.save_state()

        return session

    @classmethod
    def resume_session(
        cls,
        deaddrop: Deaddrop,
        session_id: str = None,
        namespace_secret: str = None,
        sync_from_room: bool = True,
    ) -> "CoordinationSession":
        """Resume an existing coordination session.

        Can resume by either:
        - session_id: Loads from ~/.silica/coordination/{session_id}.json
        - namespace_secret: Reconstructs state from deaddrop

        If sync_from_room is True, reads recent room history to update
        agent states based on their last messages.

        Args:
            deaddrop: Deaddrop client
            session_id: Session ID to load from file
            namespace_secret: Namespace secret to reconstruct from
            sync_from_room: Whether to sync agent states from room history

        Returns:
            Resumed CoordinationSession instance

        Raises:
            ValueError: If neither session_id nor namespace_secret provided
            FileNotFoundError: If session file doesn't exist
        """
        if session_id:
            # Load from file
            session_file = get_session_file(session_id)
            if not session_file.exists():
                raise FileNotFoundError(f"Session file not found: {session_file}")

            with open(session_file, "r") as f:
                data = json.load(f)

            state = SessionState.from_dict(data)
            session = cls(deaddrop, state)

            # Sync agent states from room history
            if sync_from_room:
                session._sync_from_room_history()

            return session

        elif namespace_secret:
            # Reconstruct from namespace secret
            # The namespace ID can be derived from the secret (deaddrop uses hash)
            # For now, we require session_id for resumption
            raise NotImplementedError(
                "Resumption from namespace_secret not yet implemented. "
                "Use session_id instead."
            )

        else:
            raise ValueError("Either session_id or namespace_secret must be provided")

    def _sync_from_room_history(self) -> dict[str, Any]:
        """Sync agent states from room history.

        Reads recent messages from the coordination room to update:
        - Agent states (idle vs working)
        - Last seen timestamps
        - Pending permission requests

        Returns:
            Dict with sync results (agents_updated, permissions_found)
        """
        from .protocol import (
            Idle,
            Progress,
            Result,
            TaskAck,
            PermissionRequest,
            deserialize_message,
        )
        from .compression import decompress_payload

        results = {
            "agents_updated": 0,
            "permissions_found": 0,
            "messages_processed": 0,
        }

        try:
            # Get room messages (use coordinator identity secret to read)
            room_messages = self.deaddrop.get_room_messages(
                ns=self.namespace_id,
                room_id=self.state.room_id,
                secret=self.state.coordinator_secret,
            )
        except Exception:
            # Room may not exist or we may not have access
            return results

        # Track the most recent state-relevant message per agent
        agent_latest_state: dict[
            str, tuple[str, str]
        ] = {}  # agent_id -> (state, timestamp)

        for raw_msg in room_messages:
            results["messages_processed"] += 1

            # Get sender identity
            sender_id = raw_msg.get("from") or raw_msg.get("sender_id")
            if not sender_id:
                continue

            # Find agent by identity
            agent = self.get_agent_by_identity(sender_id)
            if not agent:
                continue

            # Parse message content (field name varies: "body" or "content")
            content = raw_msg.get("body") or raw_msg.get("content", "")
            content_type = raw_msg.get("content_type", "")

            if content_type != "application/vnd.silica.coordination+json":
                continue

            try:
                # Check for compression
                compression = None
                if "compression=" in content_type:
                    for part in content_type.split(";"):
                        part = part.strip()
                        if part.startswith("compression="):
                            compression = part.split("=", 1)[1]
                            break

                # Decompress if needed
                decompressed = decompress_payload(content, compression)

                # Parse JSON if still needed
                if isinstance(decompressed, str):
                    msg_data = json.loads(decompressed)
                else:
                    msg_data = decompressed

                message = deserialize_message(msg_data)
            except Exception:
                continue

            # Get timestamp
            timestamp = raw_msg.get("created_at") or raw_msg.get("timestamp", "")

            # Determine state from message type
            if isinstance(message, Idle):
                new_state = "idle"
            elif isinstance(message, (Progress, TaskAck)):
                new_state = "working"
            elif isinstance(message, Result):
                # Result could mean task complete (idle) or termination
                if message.status == "terminated":
                    new_state = "terminated"
                else:
                    new_state = "idle"  # Task complete, waiting for next
            elif isinstance(message, PermissionRequest):
                new_state = "waiting_permission"
                # Track as pending if not already in our queue
                if message.request_id not in self.state.pending_permissions:
                    self.queue_permission(
                        request_id=message.request_id,
                        agent_id=agent.agent_id,
                        action=message.action,
                        resource=message.resource,
                        context=message.context,
                    )
                    results["permissions_found"] += 1
            else:
                continue

            # Update if this is newer than what we have
            current = agent_latest_state.get(agent.agent_id)
            if not current or timestamp > current[1]:
                agent_latest_state[agent.agent_id] = (new_state, timestamp)

        # Apply state updates
        for agent_id, (state_str, timestamp) in agent_latest_state.items():
            agent = self.get_agent(agent_id)
            if agent and agent.state != AgentState.TERMINATED:
                try:
                    new_state = AgentState(state_str)
                    if agent.state != new_state:
                        self.update_agent_state(agent_id, new_state)
                        results["agents_updated"] += 1
                    # Always update last_seen
                    agent.last_seen = timestamp
                except ValueError:
                    pass

        self.save_state()
        return results

    def sync_agent_states(self) -> dict[str, Any]:
        """Manually trigger agent state sync from room history.

        Call this to refresh agent states when resuming a session
        or when you suspect state may be stale.

        Returns:
            Dict with sync results
        """
        return self._sync_from_room_history()

    def save_state(self) -> Path:
        """Persist session state to disk.

        Returns:
            Path to the saved state file
        """
        session_file = get_session_file(self.session_id)
        with open(session_file, "w") as f:
            json.dump(self.state.to_dict(), f, indent=2)
        return session_file

    def get_state(self) -> dict[str, Any]:
        """Get current session state as dict."""
        return self.state.to_dict()

    # --- Agent Registry ---

    def register_agent(
        self,
        agent_id: str,
        identity_id: str,
        display_name: str,
        workspace_name: str,
    ) -> AgentInfo:
        """Register a new agent in the session.

        Args:
            agent_id: Unique agent identifier
            identity_id: Deaddrop identity ID for the agent
            display_name: Human-readable name
            workspace_name: Silica remote workspace name

        Returns:
            AgentInfo for the registered agent
        """
        agent = AgentInfo(
            agent_id=agent_id,
            identity_id=identity_id,
            display_name=display_name,
            workspace_name=workspace_name,
            state=AgentState.SPAWNING,
        )
        self.state.agents[agent_id] = agent
        self.save_state()
        return agent

    def update_agent_state(
        self,
        agent_id: str,
        state: AgentState,
        task_id: str = None,
        tmux_session: str = None,
    ) -> AgentInfo:
        """Update an agent's state.

        Args:
            agent_id: Agent to update
            state: New state
            task_id: Associated task ID (for WORKING state)
            tmux_session: tmux session name (for local workers)

        Returns:
            Updated AgentInfo

        Raises:
            KeyError: If agent not found
        """
        agent = self.state.agents[agent_id]
        agent.state = state
        agent.last_seen = datetime.utcnow().isoformat()
        if task_id is not None:
            agent.current_task_id = task_id
        elif state == AgentState.IDLE:
            agent.current_task_id = None
        if tmux_session is not None:
            agent.tmux_session = tmux_session
        self.save_state()
        return agent

    def update_agent_last_seen(self, agent_id: str) -> AgentInfo:
        """Update an agent's last_seen timestamp.

        Args:
            agent_id: Agent to update

        Returns:
            Updated AgentInfo
        """
        agent = self.state.agents[agent_id]
        agent.last_seen = datetime.utcnow().isoformat()
        self.save_state()
        return agent

    def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        """Get agent info by ID."""
        return self.state.agents.get(agent_id)

    def get_agent_by_identity(self, identity_id: str) -> Optional[AgentInfo]:
        """Get agent info by deaddrop identity ID."""
        for agent in self.state.agents.values():
            if agent.identity_id == identity_id:
                return agent
        return None

    def list_agents(
        self,
        state_filter: AgentState = None,
    ) -> list[AgentInfo]:
        """List all registered agents.

        Args:
            state_filter: Optional filter by state

        Returns:
            List of AgentInfo objects
        """
        agents = list(self.state.agents.values())
        if state_filter:
            agents = [a for a in agents if a.state == state_filter]
        return agents

    def remove_agent(self, agent_id: str) -> Optional[AgentInfo]:
        """Remove an agent from the registry.

        Args:
            agent_id: Agent to remove

        Returns:
            Removed AgentInfo, or None if not found
        """
        agent = self.state.agents.pop(agent_id, None)
        if agent:
            self.save_state()
        return agent

    # --- Human Participants ---

    def register_human(
        self,
        identity_id: str,
        display_name: str,
    ) -> HumanParticipant:
        """Register a human participant.

        Args:
            identity_id: Deaddrop identity ID
            display_name: Human-readable name

        Returns:
            HumanParticipant info
        """
        human = HumanParticipant(
            identity_id=identity_id,
            display_name=display_name,
        )
        self.state.humans[identity_id] = human
        self.save_state()
        return human

    def get_human(self, identity_id: str) -> Optional[HumanParticipant]:
        """Get human participant by identity ID."""
        return self.state.humans.get(identity_id)

    def list_humans(self) -> list[HumanParticipant]:
        """List all human participants."""
        return list(self.state.humans.values())

    # --- Utility Methods ---

    def add_agent_to_room(self, agent_id: str) -> bool:
        """Add an agent to the coordination room.

        Args:
            agent_id: Agent to add

        Returns:
            True if added successfully
        """
        agent = self.get_agent(agent_id)
        if not agent:
            return False

        try:
            self.deaddrop.add_room_member(
                ns=self.namespace_id,
                room_id=self.state.room_id,
                identity_id=agent.identity_id,
                secret=self.state.coordinator_secret,
            )
            return True
        except Exception:
            return False

    def add_human_to_room(self, identity_id: str) -> bool:
        """Add a human to the coordination room.

        Args:
            identity_id: Human's identity ID

        Returns:
            True if added successfully
        """
        try:
            self.deaddrop.add_room_member(
                ns=self.namespace_id,
                room_id=self.state.room_id,
                identity_id=identity_id,
                secret=self.state.coordinator_secret,
            )
            return True
        except Exception:
            return False

    # --- Permission Queue ---

    def queue_permission(
        self,
        request_id: str,
        agent_id: str,
        action: str,
        resource: str,
        context: str,
    ) -> PendingPermission:
        """Queue a permission request that timed out.

        Args:
            request_id: Unique request identifier
            agent_id: Agent that made the request
            action: The action being requested
            resource: The resource being accessed
            context: Additional context about the request

        Returns:
            PendingPermission object
        """
        pending = PendingPermission(
            request_id=request_id,
            agent_id=agent_id,
            action=action,
            resource=resource,
            context=context,
        )
        self.state.pending_permissions[request_id] = pending
        self.save_state()
        return pending

    def get_pending_permission(self, request_id: str) -> Optional[PendingPermission]:
        """Get a pending permission by request ID."""
        return self.state.pending_permissions.get(request_id)

    def list_pending_permissions(
        self,
        agent_id: str = None,
        status: str = None,
    ) -> list[PendingPermission]:
        """List pending permissions.

        Args:
            agent_id: Optional filter by agent
            status: Optional filter by status (pending, granted, denied, expired)

        Returns:
            List of PendingPermission objects
        """
        permissions = list(self.state.pending_permissions.values())
        if agent_id:
            permissions = [p for p in permissions if p.agent_id == agent_id]
        if status:
            permissions = [p for p in permissions if p.status == status]
        return permissions

    def update_pending_permission(
        self,
        request_id: str,
        status: str,
    ) -> Optional[PendingPermission]:
        """Update a pending permission's status.

        Args:
            request_id: Request to update
            status: New status (granted, denied, expired)

        Returns:
            Updated PendingPermission, or None if not found
        """
        pending = self.state.pending_permissions.get(request_id)
        if pending:
            pending.status = status
            self.save_state()
        return pending

    def remove_pending_permission(self, request_id: str) -> Optional[PendingPermission]:
        """Remove a pending permission from the queue.

        Args:
            request_id: Request to remove

        Returns:
            Removed PendingPermission, or None if not found
        """
        pending = self.state.pending_permissions.pop(request_id, None)
        if pending:
            self.save_state()
        return pending

    def clear_expired_permissions(self, max_age_hours: int = 24) -> int:
        """Clear permissions older than the specified age.

        Args:
            max_age_hours: Maximum age in hours before expiring

        Returns:
            Number of permissions cleared
        """
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        to_remove = []

        for request_id, pending in self.state.pending_permissions.items():
            try:
                requested_at = datetime.fromisoformat(pending.requested_at)
                if requested_at < cutoff:
                    to_remove.append(request_id)
            except (ValueError, TypeError):
                continue

        for request_id in to_remove:
            self.state.pending_permissions[request_id].status = "expired"

        if to_remove:
            self.save_state()

        return len(to_remove)


def list_sessions() -> list[dict[str, Any]]:
    """List all saved coordination sessions.

    Returns:
        List of session info dicts (session_id, display_name, created_at)
    """
    sessions_dir = get_sessions_dir()
    sessions = []

    for path in sessions_dir.glob("*.json"):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            sessions.append(
                {
                    "session_id": data.get("session_id"),
                    "display_name": data.get("display_name"),
                    "created_at": data.get("created_at"),
                    "agent_count": len(data.get("agents", {})),
                }
            )
        except (json.JSONDecodeError, IOError):
            continue

    return sorted(sessions, key=lambda s: s.get("created_at", ""), reverse=True)


def delete_session(session_id: str) -> bool:
    """Delete a session's saved state.

    Args:
        session_id: Session to delete

    Returns:
        True if deleted, False if not found
    """
    session_file = get_session_file(session_id)
    if session_file.exists():
        session_file.unlink()
        return True
    return False
