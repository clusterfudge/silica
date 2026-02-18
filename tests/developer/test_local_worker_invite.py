"""Tests for local deaddrop invite handling in worker bootstrap.

Verifies that workers spawned by a coordinator using a local (SQLite-backed)
deaddrop can correctly claim invites and connect to the coordination namespace.
"""

import os
import pytest
import tempfile
from unittest.mock import patch

from deadrop import Deaddrop

from silica.developer.coordination.worker_bootstrap import (
    _create_deaddrop_for_invite,
    claim_invite_and_connect,
    DEADDROP_INVITE_URL,
    COORDINATION_AGENT_ID,
)
from silica.developer.coordination.session import CoordinationSession


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
def clean_env():
    """Clean coordination environment variables."""
    old_invite = os.environ.pop(DEADDROP_INVITE_URL, None)
    old_agent_id = os.environ.pop(COORDINATION_AGENT_ID, None)
    yield
    if old_invite:
        os.environ[DEADDROP_INVITE_URL] = old_invite
    else:
        os.environ.pop(DEADDROP_INVITE_URL, None)
    if old_agent_id:
        os.environ[COORDINATION_AGENT_ID] = old_agent_id
    else:
        os.environ.pop(COORDINATION_AGENT_ID, None)


class TestCreateDeaddropForInvite:
    """Test _create_deaddrop_for_invite URL scheme handling."""

    def test_http_url_creates_remote(self):
        """Should create remote deaddrop for http:// URLs."""
        dd = _create_deaddrop_for_invite("http://example.com/join/abc#key")
        assert dd is not None

    def test_https_url_creates_remote(self):
        """Should create remote deaddrop for https:// URLs."""
        dd = _create_deaddrop_for_invite("https://example.com/join/abc#key")
        assert dd is not None

    def test_local_file_url_creates_local(self):
        """Should create local deaddrop for local:// file-based URLs."""
        with tempfile.TemporaryDirectory() as td:
            # Create a local deaddrop first so the path exists
            Deaddrop.create_local(path=td)

            url = f"local://{td}/join/abc123#key456"
            dd = _create_deaddrop_for_invite(url)
            assert dd is not None

    def test_local_memory_url_raises(self):
        """Should raise for in-memory local:// URLs (can't share between processes)."""
        with pytest.raises(RuntimeError, match="In-memory deaddrop cannot be shared"):
            _create_deaddrop_for_invite("local://:memory:/join/abc#key")

    def test_local_empty_path_raises(self):
        """Should raise when deaddrop path cannot be extracted."""
        # This URL has no path before /join/
        with pytest.raises(RuntimeError, match="Could not extract deaddrop path"):
            _create_deaddrop_for_invite("local:///join/abc#key")

    def test_unsupported_scheme_raises(self):
        """Should raise for unknown URL schemes."""
        with pytest.raises(RuntimeError, match="Unsupported invite URL scheme"):
            _create_deaddrop_for_invite("ftp://example.com/invite/abc")

    def test_local_url_extracts_correct_path(self):
        """Should correctly extract the deaddrop dir from the invite URL."""
        with tempfile.TemporaryDirectory() as td:
            Deaddrop.create_local(path=td)
            url = f"local://{td}/join/someinviteid#somekey"
            dd = _create_deaddrop_for_invite(url)
            assert dd is not None


class TestLocalInviteEndToEnd:
    """End-to-end tests: coordinator creates local invite, worker claims it."""

    def test_local_invite_claim_roundtrip(self, temp_sessions_dir, clean_env):
        """Full roundtrip: create session with local deaddrop, create invite, claim it."""
        with tempfile.TemporaryDirectory() as td:
            # Create local deaddrop (like coordinator --local does)
            dd = Deaddrop.create_local(path=td)

            # Create a coordination session
            session = CoordinationSession.create_session(dd, "Test Session")

            # Create a worker identity (like spawn_agent does)
            worker_identity = dd.create_identity(
                ns=session.namespace_id,
                display_name="Test Worker",
                ns_secret=session.namespace_secret,
            )

            # Create an invite for the worker
            invite = dd.create_invite(
                ns=session.namespace_id,
                identity_id=worker_identity["id"],
                identity_secret=worker_identity["secret"],
                ns_secret=session.namespace_secret,
                display_name="Worker: Test Worker",
            )

            invite_url = invite["invite_url"]

            # Verify the URL is local://
            assert invite_url.startswith("local://")

            # Add coordination metadata (like spawn_agent does)
            from urllib.parse import urlencode, urlparse, urlunparse

            parsed = urlparse(invite_url)
            coord_params = urlencode(
                {
                    "room": session.state.room_id,
                    "coordinator": session.state.coordinator_id,
                }
            )
            new_query = (
                f"{parsed.query}&{coord_params}" if parsed.query else coord_params
            )
            full_invite_url = urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    new_query,
                    parsed.fragment,
                )
            )

            # Set agent ID env var (like spawn_agent does)
            os.environ[COORDINATION_AGENT_ID] = "test-agent-1"

            # Worker claims the invite (the critical path that was broken)
            result = claim_invite_and_connect(invite_url=full_invite_url)

            # Verify the result
            assert result.agent_id == "test-agent-1"
            assert result.namespace_id == session.namespace_id
            assert result.room_id == session.state.room_id
            assert result.coordinator_id == session.state.coordinator_id
            assert result.context is not None

    def test_local_worker_can_message_coordinator(self, temp_sessions_dir, clean_env):
        """Worker claimed via local invite can send messages to coordinator."""
        with tempfile.TemporaryDirectory() as td:
            dd = Deaddrop.create_local(path=td)
            session = CoordinationSession.create_session(dd, "Test Session")

            worker_identity = dd.create_identity(
                ns=session.namespace_id,
                display_name="Messaging Worker",
                ns_secret=session.namespace_secret,
            )

            invite = dd.create_invite(
                ns=session.namespace_id,
                identity_id=worker_identity["id"],
                identity_secret=worker_identity["secret"],
                ns_secret=session.namespace_secret,
                display_name="Worker: Messaging Worker",
            )

            from urllib.parse import urlencode, urlparse, urlunparse

            parsed = urlparse(invite["invite_url"])
            coord_params = urlencode(
                {
                    "room": session.state.room_id,
                    "coordinator": session.state.coordinator_id,
                }
            )
            full_url = urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    coord_params,
                    parsed.fragment,
                )
            )

            os.environ[COORDINATION_AGENT_ID] = "worker-msg-1"

            result = claim_invite_and_connect(invite_url=full_url)

            # Worker sends an Idle message to the coordinator
            from silica.developer.coordination import Idle

            idle_msg = Idle(agent_id="worker-msg-1")
            result.context.send_to_coordinator(idle_msg)

            # Coordinator should receive it
            coordinator_messages = session.context.receive_messages(
                wait=0, include_room=False
            )

            # Filter for Idle messages
            idle_received = [
                m for m in coordinator_messages if isinstance(m.message, Idle)
            ]
            assert len(idle_received) == 1
            assert idle_received[0].message.agent_id == "worker-msg-1"

    def test_coordinator_can_send_task_to_local_worker(
        self, temp_sessions_dir, clean_env
    ):
        """Coordinator can send a task to a worker connected via local invite."""
        with tempfile.TemporaryDirectory() as td:
            dd = Deaddrop.create_local(path=td)
            session = CoordinationSession.create_session(dd, "Test Session")

            worker_identity = dd.create_identity(
                ns=session.namespace_id,
                display_name="Task Worker",
                ns_secret=session.namespace_secret,
            )

            # Register the agent (like spawn_agent does)
            session.register_agent(
                agent_id="worker-task-1",
                identity_id=worker_identity["id"],
                display_name="Task Worker",
                workspace_name="test-workspace",
            )
            session.add_agent_to_room("worker-task-1")

            invite = dd.create_invite(
                ns=session.namespace_id,
                identity_id=worker_identity["id"],
                identity_secret=worker_identity["secret"],
                ns_secret=session.namespace_secret,
                display_name="Worker: Task Worker",
            )

            from urllib.parse import urlencode, urlparse, urlunparse

            parsed = urlparse(invite["invite_url"])
            coord_params = urlencode(
                {
                    "room": session.state.room_id,
                    "coordinator": session.state.coordinator_id,
                }
            )
            full_url = urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    coord_params,
                    parsed.fragment,
                )
            )

            os.environ[COORDINATION_AGENT_ID] = "worker-task-1"

            result = claim_invite_and_connect(invite_url=full_url)

            # Coordinator sends a task to the worker
            from silica.developer.coordination import TaskAssign

            task = TaskAssign(
                task_id="task-001",
                description="Do something useful",
                context={"key": "value"},
            )
            session.context.send_message(worker_identity["id"], task)

            # Worker receives it
            worker_messages = result.context.receive_messages(
                wait=0, include_room=False
            )
            task_messages = [
                m for m in worker_messages if isinstance(m.message, TaskAssign)
            ]
            assert len(task_messages) == 1
            assert task_messages[0].message.task_id == "task-001"
            assert task_messages[0].message.description == "Do something useful"


class TestRemoteInviteStillWorks:
    """Verify that remote (http/https) invite handling still works."""

    def test_claim_invite_remote_url(self, temp_sessions_dir, clean_env):
        """Remote invite URL should still work through mocked Deaddrop.remote."""
        with patch(
            "silica.developer.coordination.worker_bootstrap.Deaddrop"
        ) as MockDeaddrop:
            mock_dd = Deaddrop.in_memory()
            ns = mock_dd.create_namespace(display_name="test")
            ident = mock_dd.create_identity(
                ns=ns["ns"], display_name="Worker", ns_secret=ns["secret"]
            )

            # Mock Deaddrop.remote() to return our in-memory instance
            MockDeaddrop.remote.return_value = mock_dd
            mock_dd_claim = {
                "identity_id": ident["id"],
                "secret": ident["secret"],
                "ns": ns["ns"],
                "display_name": "Test Worker",
            }

            # Patch claim_invite to return our data
            def mock_claim(url):
                return mock_dd_claim

            mock_dd.claim_invite = mock_claim

            invite_url = (
                "https://example.com/join/abc123"
                "?room=room-123&coordinator=coord-456#key456"
            )
            os.environ[COORDINATION_AGENT_ID] = "remote-worker-1"

            result = claim_invite_and_connect(invite_url=invite_url)

            assert result.agent_id == "remote-worker-1"
            assert result.room_id == "room-123"
            assert result.coordinator_id == "coord-456"
            assert result.context is not None
