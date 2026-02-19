"""Tests for the v2 split-file flush behavior in AgentContext."""

import json
import tempfile
import shutil
from pathlib import Path

import pytest

from silica.developer.context import AgentContext
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.session_store import SessionStore, SESSION_FORMAT_VERSION
from silica.developer.memory import MemoryManager
from silica.developer.user_interface import UserInterface


class MockUI(UserInterface):
    def __init__(self):
        self.messages = []

    def handle_system_message(self, message, markdown=True):
        self.messages.append(message)

    def permission_callback(
        self, action, resource, sandbox_mode, action_arguments, group=None
    ):
        return True

    def permission_rendering_callback(self, action, resource, action_arguments):
        pass

    def bare(self, message):
        pass

    def display_token_count(
        self,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        total_cost,
        cached_tokens=None,
        conversation_size=None,
        context_window=None,
    ):
        pass

    def display_welcome_message(self):
        pass

    def get_user_input(self, prompt=""):
        return ""

    def handle_assistant_message(self, message, markdown=True):
        pass

    def handle_tool_result(self, name, result, markdown=True):
        pass

    def handle_tool_use(self, tool_name, tool_params):
        pass

    def handle_user_input(self, user_input):
        pass

    def status(self, message, spinner=None):
        class Noop:
            def __enter__(self):
                return None

            def __exit__(self, *a):
                pass

        return Noop()


MODEL_SPEC = {
    "title": "claude-sonnet-4-20250514",
    "pricing": {"input": 3.0, "output": 15.0},
    "cache_pricing": {"write": 3.75, "read": 0.30},
    "max_tokens": 8192,
    "context_window": 200000,
}


@pytest.fixture
def test_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


def _make_context(test_dir, session_id="test-session", parent_session_id=None):
    return AgentContext(
        parent_session_id=parent_session_id,
        session_id=session_id,
        model_spec=MODEL_SPEC,
        sandbox=Sandbox(test_dir, mode=SandboxMode.ALLOW_ALL),
        user_interface=MockUI(),
        usage=[],
        memory_manager=MemoryManager(),
        history_base_dir=Path(test_dir) / ".silica" / "personas" / "default",
    )


def _history_dir(test_dir, session_id="test-session"):
    return Path(test_dir) / ".silica" / "personas" / "default" / "history" / session_id


class TestFlushCreatesV2Files:
    """flush() should create all 4 v2 split files."""

    def test_flush_creates_all_files(self, test_dir):
        ctx = _make_context(test_dir)
        ctx._chat_history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        # Add usage so metadata.jsonl gets created
        ctx.usage.append(
            (
                {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                MODEL_SPEC,
            )
        )
        ctx.flush(ctx.chat_history, compact=False)

        hdir = _history_dir(test_dir)
        assert (hdir / "session.json").exists()
        assert (hdir / "root.history.jsonl").exists()
        assert (hdir / "root.metadata.jsonl").exists()
        assert (hdir / "root.context.jsonl").exists()
        # Legacy dual-write removed — root.json no longer created by flush
        assert not (hdir / "root.json").exists()

    def test_session_json_has_correct_fields(self, test_dir):
        ctx = _make_context(test_dir, session_id="sid-123")
        ctx._chat_history = [{"role": "user", "content": "hi"}]
        ctx.flush(ctx.chat_history, compact=False)

        meta = json.loads(
            (_history_dir(test_dir, "sid-123") / "session.json").read_text()
        )
        assert meta["version"] == SESSION_FORMAT_VERSION
        assert meta["session_id"] == "sid-123"
        assert meta["thinking_mode"] == "max"
        assert "created_at" in meta
        assert "last_updated" in meta


class TestIncrementalFlush:
    """Repeated flushes should append only new messages to history."""

    def test_two_flushes_no_duplicates(self, test_dir):
        ctx = _make_context(test_dir)
        ctx._chat_history = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
        ]
        ctx.flush(ctx.chat_history, compact=False)

        # Add 2 more messages
        ctx._chat_history.append({"role": "user", "content": "msg3"})
        ctx._chat_history.append({"role": "assistant", "content": "msg4"})
        ctx.flush(ctx.chat_history, compact=False)

        store = SessionStore(_history_dir(test_dir))
        history = store.read_history()
        assert len(history) == 4
        assert history[0]["content"] == "msg1"
        assert history[3]["content"] == "msg4"

    def test_msg_ids_sequential_across_flushes(self, test_dir):
        ctx = _make_context(test_dir)
        ctx._chat_history = [{"role": "user", "content": "a"}]
        ctx.flush(ctx.chat_history, compact=False)

        ctx._chat_history.append({"role": "assistant", "content": "b"})
        ctx.flush(ctx.chat_history, compact=False)

        store = SessionStore(_history_dir(test_dir))
        history = store.read_history()
        assert history[0]["msg_id"] == "m_0001"
        assert history[1]["msg_id"] == "m_0002"

    def test_prev_msg_ids_chain_correctly(self, test_dir):
        ctx = _make_context(test_dir)
        ctx._chat_history = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        ctx.flush(ctx.chat_history, compact=False)

        ctx._chat_history.append({"role": "user", "content": "c"})
        ctx.flush(ctx.chat_history, compact=False)

        store = SessionStore(_history_dir(test_dir))
        history = store.read_history()
        assert history[0]["prev_msg_id"] is None
        assert history[1]["prev_msg_id"] == "m_0001"
        assert history[2]["prev_msg_id"] == "m_0002"

    def test_context_matches_full_chat_history(self, test_dir):
        ctx = _make_context(test_dir)
        ctx._chat_history = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        ctx.flush(ctx.chat_history, compact=False)

        store = SessionStore(_history_dir(test_dir))
        context = store.read_context()
        assert len(context) == 2
        assert context[0]["role"] == "user"
        assert context[1]["content"] == "b"

    def test_no_flush_when_empty(self, test_dir):
        ctx = _make_context(test_dir)
        ctx.flush([], compact=False)
        hdir = _history_dir(test_dir)
        assert not hdir.exists()


class TestUsageMetadata:
    """Usage entries should be written to metadata.jsonl."""

    def test_usage_written_to_metadata(self, test_dir):
        ctx = _make_context(test_dir)
        ctx._chat_history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        # Simulate an API call's usage
        ctx.usage.append(
            (
                {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                MODEL_SPEC,
            )
        )
        ctx.flush(ctx.chat_history, compact=False)

        store = SessionStore(_history_dir(test_dir))
        metadata = store.read_metadata()
        assert len(metadata) == 1
        assert metadata[0]["usage"]["input_tokens"] == 100
        assert metadata[0]["model"] == "claude-sonnet-4-20250514"

    def test_incremental_usage_no_duplicates(self, test_dir):
        ctx = _make_context(test_dir)
        ctx._chat_history = [{"role": "user", "content": "a"}]
        ctx.usage.append(
            (
                {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                MODEL_SPEC,
            )
        )
        ctx.flush(ctx.chat_history, compact=False)

        ctx._chat_history.append({"role": "assistant", "content": "b"})
        ctx.usage.append(
            (
                {
                    "input_tokens": 20,
                    "output_tokens": 10,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                MODEL_SPEC,
            )
        )
        ctx.flush(ctx.chat_history, compact=False)

        store = SessionStore(_history_dir(test_dir))
        metadata = store.read_metadata()
        assert len(metadata) == 2
        assert metadata[0]["usage"]["input_tokens"] == 10
        assert metadata[1]["usage"]["input_tokens"] == 20


class TestLoadV2Session:
    """load_session_data should load from v2 format."""

    def test_load_from_v2_format(self, test_dir):
        from silica.developer.context import load_session_data

        # Create and flush a session
        ctx = _make_context(test_dir, session_id="load-test")
        ctx._chat_history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        ctx.usage.append(
            (
                {
                    "input_tokens": 50,
                    "output_tokens": 25,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                MODEL_SPEC,
            )
        )
        ctx.flush(ctx.chat_history, compact=False)

        # Now load it
        base_ctx = _make_context(test_dir, session_id="load-test")
        loaded = load_session_data(
            "load-test",
            base_ctx,
            history_base_dir=Path(test_dir) / ".silica" / "personas" / "default",
        )

        assert loaded is not None
        assert len(loaded.chat_history) == 2
        assert loaded.chat_history[0]["content"] == "hello"
        assert loaded.session_id == "load-test"

    def test_load_sets_flush_counters(self, test_dir):
        from silica.developer.context import load_session_data

        ctx = _make_context(test_dir, session_id="counter-test")
        ctx._chat_history = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ]
        ctx.flush(ctx.chat_history, compact=False)

        base_ctx = _make_context(test_dir, session_id="counter-test")
        loaded = load_session_data(
            "counter-test",
            base_ctx,
            history_base_dir=Path(test_dir) / ".silica" / "personas" / "default",
        )

        assert loaded._last_flushed_msg_count == 3

    def test_flush_after_load_appends_only_new(self, test_dir):
        from silica.developer.context import load_session_data

        ctx = _make_context(test_dir, session_id="append-test")
        ctx._chat_history = [
            {"role": "user", "content": "original"},
        ]
        ctx.flush(ctx.chat_history, compact=False)

        # Load and add new messages
        base_ctx = _make_context(test_dir, session_id="append-test")
        loaded = load_session_data(
            "append-test",
            base_ctx,
            history_base_dir=Path(test_dir) / ".silica" / "personas" / "default",
        )
        loaded._chat_history.append({"role": "assistant", "content": "new"})
        loaded.flush(loaded.chat_history, compact=False)

        store = SessionStore(_history_dir(test_dir, "append-test"))
        history = store.read_history()
        # Should have 2 total messages (1 original + 1 new), not 3 (duplicated original)
        assert len(history) == 2
        assert history[0]["content"] == "original"
        assert history[1]["content"] == "new"


class TestLoadLegacyFallback:
    """load_session_data should fall back to legacy root.json."""

    def test_load_from_legacy_format(self, test_dir):
        from silica.developer.context import load_session_data

        hdir = (
            Path(test_dir)
            / ".silica"
            / "personas"
            / "default"
            / "history"
            / "legacy-sess"
        )
        hdir.mkdir(parents=True)
        legacy_data = {
            "session_id": "legacy-sess",
            "parent_session_id": None,
            "model_spec": MODEL_SPEC,
            "usage": [],
            "messages": [
                {"role": "user", "content": "old message"},
                {"role": "assistant", "content": "old reply"},
            ],
            "thinking_mode": "max",
            "metadata": {
                "created_at": "2025-01-01T00:00:00Z",
                "last_updated": "2025-01-01T00:00:00Z",
            },
        }
        (hdir / "root.json").write_text(json.dumps(legacy_data))

        base_ctx = _make_context(test_dir, session_id="legacy-sess")
        loaded = load_session_data(
            "legacy-sess",
            base_ctx,
            history_base_dir=Path(test_dir) / ".silica" / "personas" / "default",
        )

        assert loaded is not None
        assert len(loaded.chat_history) == 2
        assert loaded.chat_history[0]["content"] == "old message"
