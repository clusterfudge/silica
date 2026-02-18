"""Tests for the v2 session storage module."""

import json

import pytest

from silica.developer.session_store import SessionStore, SESSION_FORMAT_VERSION


@pytest.fixture
def session_dir(tmp_path):
    """Create a temporary session directory."""
    d = tmp_path / "test-session-id"
    d.mkdir()
    return d


class TestSessionStoreConstruction:
    """Tests for SessionStore initialization."""

    def test_root_agent_defaults(self, session_dir):
        store = SessionStore(session_dir, agent_name="root")
        assert store.agent_name == "root"
        assert store._id_prefix == "m_"
        assert store._msg_seq == 0

    def test_sub_agent_prefix(self, session_dir):
        sub_id = "abc12345-6789-abcd-ef01-234567890abc"
        store = SessionStore(session_dir, agent_name=sub_id)
        assert store._id_prefix == "m_abc12345_"

    def test_msg_seq_initialized_from_empty_dir(self, session_dir):
        store = SessionStore(session_dir)
        assert store._msg_seq == 0
        assert store.last_msg_id is None

    def test_msg_seq_initialized_from_existing_history(self, session_dir):
        # Pre-populate history.jsonl
        history = session_dir / "root.history.jsonl"
        history.write_text(
            '{"msg_id": "m_0001", "role": "user", "content": "hi"}\n'
            '{"msg_id": "m_0002", "role": "assistant", "content": "hello"}\n'
            '{"msg_id": "m_0003", "role": "user", "content": "bye"}\n'
        )
        store = SessionStore(session_dir, agent_name="root")
        assert store._msg_seq == 3
        assert store.last_msg_id == "m_0003"

    def test_sub_agent_msg_seq_from_existing(self, session_dir):
        sub_id = "deadbeef-1234"
        history = session_dir / f"{sub_id}.history.jsonl"
        history.write_text(
            '{"msg_id": "m_deadbeef_0001", "role": "user", "content": "hi"}\n'
            '{"msg_id": "m_deadbeef_0002", "role": "assistant", "content": "yo"}\n'
        )
        store = SessionStore(session_dir, agent_name=sub_id)
        assert store._msg_seq == 2


class TestMessageIds:
    """Tests for msg_id generation."""

    def test_next_msg_id_sequential(self, session_dir):
        store = SessionStore(session_dir)
        assert store.next_msg_id() == "m_0001"
        assert store.next_msg_id() == "m_0002"
        assert store.next_msg_id() == "m_0003"

    def test_peek_does_not_advance(self, session_dir):
        store = SessionStore(session_dir)
        assert store.peek_msg_id() == "m_0001"
        assert store.peek_msg_id() == "m_0001"
        assert store.next_msg_id() == "m_0001"
        assert store.peek_msg_id() == "m_0002"

    def test_sub_agent_msg_ids(self, session_dir):
        store = SessionStore(session_dir, agent_name="abcd1234-rest-of-id")
        assert store.next_msg_id() == "m_abcd1234_0001"
        assert store.next_msg_id() == "m_abcd1234_0002"

    def test_last_msg_id(self, session_dir):
        store = SessionStore(session_dir)
        assert store.last_msg_id is None
        store.next_msg_id()
        assert store.last_msg_id == "m_0001"


class TestSessionMeta:
    """Tests for session.json read/write."""

    def test_write_and_read(self, session_dir):
        store = SessionStore(session_dir)
        store.write_session_meta(
            {
                "session_id": "test-123",
                "thinking_mode": "max",
            }
        )
        meta = store.read_session_meta()
        assert meta["session_id"] == "test-123"
        assert meta["version"] == SESSION_FORMAT_VERSION
        assert "created_at" in meta
        assert "last_updated" in meta

    def test_preserves_created_at(self, session_dir):
        store = SessionStore(session_dir)
        store.write_session_meta(
            {"session_id": "test", "created_at": "2025-01-01T00:00:00Z"}
        )
        first_created = store.read_session_meta()["created_at"]

        store.write_session_meta({"session_id": "test"})
        second_meta = store.read_session_meta()
        assert second_meta["created_at"] == first_created
        assert second_meta["last_updated"] != first_created

    def test_read_nonexistent(self, session_dir):
        store = SessionStore(session_dir)
        assert store.read_session_meta() is None


class TestHistoryAppend:
    """Tests for history.jsonl append operations."""

    def test_append_messages_basic(self, session_dir):
        store = SessionStore(session_dir)
        ids = store.append_messages(
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ]
        )
        assert ids == ["m_0001", "m_0002"]

        history = store.read_history()
        assert len(history) == 2
        assert history[0]["msg_id"] == "m_0001"
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "hello"
        assert history[1]["msg_id"] == "m_0002"
        assert history[1]["role"] == "assistant"

    def test_prev_msg_id_chain_root(self, session_dir):
        """Root agent: first msg has prev_msg_id=None, rest chain."""
        store = SessionStore(session_dir)
        store.append_messages(
            [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "two"},
                {"role": "user", "content": "three"},
            ],
            prev_msg_id=None,
        )

        history = store.read_history()
        assert history[0]["prev_msg_id"] is None
        assert history[1]["prev_msg_id"] == "m_0001"
        assert history[2]["prev_msg_id"] == "m_0002"

    def test_prev_msg_id_chain_sub_agent(self, session_dir):
        """Sub-agent: first msg has prev_msg_id pointing to parent's msg_id."""
        store = SessionStore(session_dir, agent_name="sub12345-rest")
        store.append_messages(
            [
                {"role": "user", "content": "task"},
                {"role": "assistant", "content": "result"},
            ],
            prev_msg_id="m_0042",
        )

        history = store.read_history()
        assert history[0]["prev_msg_id"] == "m_0042"  # parent's tool_use msg
        assert history[1]["prev_msg_id"] == "m_sub12345_0001"

    def test_append_twice_no_duplicates(self, session_dir):
        """Two append calls produce sequential IDs with no gaps or dupes."""
        store = SessionStore(session_dir)
        ids1 = store.append_messages(
            [
                {"role": "user", "content": "first"},
            ]
        )
        ids2 = store.append_messages(
            [
                {"role": "user", "content": "second"},
            ],
            prev_msg_id=ids1[-1],
        )

        assert ids1 == ["m_0001"]
        assert ids2 == ["m_0002"]

        history = store.read_history()
        assert len(history) == 2
        assert history[0]["msg_id"] == "m_0001"
        assert history[1]["msg_id"] == "m_0002"
        assert history[1]["prev_msg_id"] == "m_0001"

    def test_append_empty_list(self, session_dir):
        store = SessionStore(session_dir)
        ids = store.append_messages([])
        assert ids == []
        assert store.read_history() == []

    def test_messages_include_timestamp(self, session_dir):
        store = SessionStore(session_dir)
        store.append_messages([{"role": "user", "content": "hi"}])
        history = store.read_history()
        assert "timestamp" in history[0]


class TestMetadataAppend:
    """Tests for metadata.jsonl append operations."""

    def test_append_and_read(self, session_dir):
        store = SessionStore(session_dir)
        store.append_metadata(
            [
                {
                    "msg_id": "m_0002",
                    "model": "claude-sonnet-4",
                    "usage": {"input_tokens": 100},
                },
            ]
        )
        meta = store.read_metadata()
        assert len(meta) == 1
        assert meta[0]["msg_id"] == "m_0002"
        assert meta[0]["model"] == "claude-sonnet-4"
        assert "timestamp" in meta[0]

    def test_append_multiple(self, session_dir):
        store = SessionStore(session_dir)
        store.append_metadata([{"msg_id": "m_0002", "model": "a"}])
        store.append_metadata([{"msg_id": "m_0004", "model": "b"}])
        meta = store.read_metadata()
        assert len(meta) == 2


class TestContext:
    """Tests for context.jsonl read/write."""

    def test_write_and_read(self, session_dir):
        store = SessionStore(session_dir)
        messages = [
            {"msg_id": "m_0045", "role": "user", "content": "question"},
            {"msg_id": "m_0046", "role": "assistant", "content": "answer"},
        ]
        store.write_context(messages)
        result = store.read_context()
        assert result == messages

    def test_overwrite_replaces(self, session_dir):
        store = SessionStore(session_dir)
        store.write_context([{"msg_id": "m_0001", "role": "user", "content": "old"}])
        store.write_context([{"msg_id": "m_0050", "role": "user", "content": "new"}])
        result = store.read_context()
        assert len(result) == 1
        assert result[0]["content"] == "new"

    def test_read_empty(self, session_dir):
        store = SessionStore(session_dir)
        assert store.read_context() == []

    def test_sub_agent_context_path(self, session_dir):
        sub_id = "abc12345-6789"
        store = SessionStore(session_dir, agent_name=sub_id)
        assert store.context_path == session_dir / f"{sub_id}.context.jsonl"


class TestLegacyDetection:
    """Tests for is_legacy()."""

    def test_legacy_detected(self, session_dir):
        (session_dir / "root.json").write_text("{}")
        store = SessionStore(session_dir)
        assert store.is_legacy() is True

    def test_not_legacy_with_session_json(self, session_dir):
        (session_dir / "root.json").write_text("{}")
        (session_dir / "session.json").write_text("{}")
        store = SessionStore(session_dir)
        assert store.is_legacy() is False

    def test_not_legacy_empty_dir(self, session_dir):
        store = SessionStore(session_dir)
        assert store.is_legacy() is False


class TestFilePaths:
    """Tests for file path generation."""

    def test_root_agent_paths(self, session_dir):
        store = SessionStore(session_dir, agent_name="root")
        assert store.history_path == session_dir / "root.history.jsonl"
        assert store.metadata_path == session_dir / "root.metadata.jsonl"
        assert store.context_path == session_dir / "root.context.jsonl"
        assert store.session_meta_path == session_dir / "session.json"

    def test_sub_agent_paths(self, session_dir):
        sub_id = "abc12345-6789"
        store = SessionStore(session_dir, agent_name=sub_id)
        assert store.history_path == session_dir / f"{sub_id}.history.jsonl"
        assert store.metadata_path == session_dir / f"{sub_id}.metadata.jsonl"
        assert store.context_path == session_dir / f"{sub_id}.context.jsonl"


class TestJSONLRobustness:
    """Tests for JSONL I/O edge cases."""

    def test_read_skips_blank_lines(self, session_dir):
        store = SessionStore(session_dir)
        path = session_dir / "test.jsonl"
        path.write_text('{"a": 1}\n\n{"b": 2}\n\n')
        result = store._read_jsonl(path)
        assert len(result) == 2

    def test_read_skips_corrupted_lines(self, session_dir):
        store = SessionStore(session_dir)
        path = session_dir / "test.jsonl"
        path.write_text('{"a": 1}\nnot json\n{"b": 2}\n')
        result = store._read_jsonl(path)
        assert len(result) == 2
        assert result[0]["a"] == 1
        assert result[1]["b"] == 2

    def test_read_nonexistent_returns_empty(self, session_dir):
        store = SessionStore(session_dir)
        result = store._read_jsonl(session_dir / "nonexistent.jsonl")
        assert result == []
