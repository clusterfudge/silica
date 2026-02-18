"""Tests for sub-agent v2 file handling."""

import json
import tempfile
import shutil
from pathlib import Path

import pytest

from silica.developer.context import AgentContext
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.session_store import SessionStore
from silica.developer.memory import MemoryManager
from tests.developer.test_context_flush_v2 import MockUI, MODEL_SPEC


@pytest.fixture
def test_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


def _make_root_context(test_dir, session_id="root-session"):
    return AgentContext(
        parent_session_id=None,
        session_id=session_id,
        model_spec=MODEL_SPEC,
        sandbox=Sandbox(test_dir, mode=SandboxMode.ALLOW_ALL),
        user_interface=MockUI(),
        usage=[],
        memory_manager=MemoryManager(),
        history_base_dir=Path(test_dir) / ".silica" / "personas" / "default",
    )


def _history_dir(test_dir, session_id="root-session"):
    return Path(test_dir) / ".silica" / "personas" / "default" / "history" / session_id


class TestSubAgentFileCreation:
    """Sub-agents should create their own file set."""

    def test_sub_agent_creates_own_files(self, test_dir):
        root = _make_root_context(test_dir)
        root._chat_history = [
            {"role": "user", "content": "start"},
            {"role": "assistant", "content": "ok"},
        ]
        root.flush(root.chat_history, compact=False)

        # Create sub-agent
        sub = root.with_user_interface(MockUI(), session_id="sub-abc123")
        sub._chat_history = [
            {"role": "user", "content": "subtask"},
            {"role": "assistant", "content": "done"},
        ]
        sub.flush(sub.chat_history, compact=False)

        hdir = _history_dir(test_dir)
        assert (hdir / "sub-abc123.history.jsonl").exists()
        assert (hdir / "sub-abc123.context.jsonl").exists()
        # Sub-agent also writes a legacy .json file
        assert (hdir / "sub-abc123.json").exists()

    def test_sub_agent_msg_ids_use_prefix(self, test_dir):
        root = _make_root_context(test_dir)
        root._chat_history = [{"role": "user", "content": "hi"}]
        root.flush(root.chat_history, compact=False)

        sub = root.with_user_interface(MockUI(), session_id="deadbeef-1234-5678")
        sub._chat_history = [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "result"},
        ]
        sub.flush(sub.chat_history, compact=False)

        store = SessionStore(_history_dir(test_dir), agent_name="deadbeef-1234-5678")
        history = store.read_history()
        assert history[0]["msg_id"] == "m_deadbeef_0001"
        assert history[1]["msg_id"] == "m_deadbeef_0002"


class TestSubAgentPrevMsgIdLinking:
    """Sub-agent first message should link to parent's last msg_id."""

    def test_first_msg_links_to_parent(self, test_dir):
        root = _make_root_context(test_dir)
        root._chat_history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        root.flush(root.chat_history, compact=False)

        # Parent's last msg_id should be m_0002
        root_store = SessionStore(_history_dir(test_dir))
        assert root_store.last_msg_id == "m_0002"

        sub = root.with_user_interface(MockUI(), session_id="sub-linked")
        sub._chat_history = [
            {"role": "user", "content": "subtask"},
        ]
        sub.flush(sub.chat_history, compact=False)

        sub_store = SessionStore(_history_dir(test_dir), agent_name="sub-linked")
        sub_history = sub_store.read_history()
        assert sub_history[0]["prev_msg_id"] == "m_0002"

    def test_subsequent_msgs_chain_within_sub(self, test_dir):
        root = _make_root_context(test_dir)
        root._chat_history = [{"role": "user", "content": "start"}]
        root.flush(root.chat_history, compact=False)

        sub = root.with_user_interface(MockUI(), session_id="sub-chain")
        sub._chat_history = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ]
        sub.flush(sub.chat_history, compact=False)

        sub_store = SessionStore(_history_dir(test_dir), agent_name="sub-chain")
        history = sub_store.read_history()
        assert history[0]["prev_msg_id"] == "m_0001"  # parent's msg
        assert history[1]["prev_msg_id"] == "m_sub-chai_0001"  # chain within sub
        assert history[2]["prev_msg_id"] == "m_sub-chai_0002"


class TestSubAgentFlushBehavior:
    """Sub-agent flush should not affect parent's files."""

    def test_sub_flush_does_not_modify_parent_history(self, test_dir):
        root = _make_root_context(test_dir)
        root._chat_history = [
            {"role": "user", "content": "original"},
            {"role": "assistant", "content": "root reply"},
        ]
        root.flush(root.chat_history, compact=False)

        root_store = SessionStore(_history_dir(test_dir))
        root_history_before = root_store.read_history()

        # Sub-agent writes
        sub = root.with_user_interface(MockUI(), session_id="sub-isolated")
        sub._chat_history = [
            {"role": "user", "content": "subtask"},
            {"role": "assistant", "content": "done"},
        ]
        sub.flush(sub.chat_history, compact=False)

        root_history_after = root_store.read_history()
        assert len(root_history_before) == len(root_history_after)

    def test_sub_usage_in_parent_metadata(self, test_dir):
        """Sub-agent usage appears in parent's usage list (shared)."""
        root = _make_root_context(test_dir)
        root._chat_history = [{"role": "user", "content": "go"}]
        root.flush(root.chat_history, compact=False)

        sub = root.with_user_interface(MockUI(), session_id="sub-usage")
        sub._chat_history = [{"role": "user", "content": "task"}]
        # Sub-agent reports usage to the shared usage list
        sub.usage.append(
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
        sub.flush(sub.chat_history, compact=False)

        # Since usage is a shared list, parent sees the sub-agent's usage
        assert len(root.usage) == 1
        assert root.usage[0][0]["input_tokens"] == 50


class TestSubAgentCompactInPlace:
    """compact_in_place on sub-agent should overwrite its own context."""

    def test_compact_overwrites_sub_context(self, test_dir):
        root = _make_root_context(test_dir)
        root._chat_history = [{"role": "user", "content": "start"}]
        root.flush(root.chat_history, compact=False)

        sub = root.with_user_interface(MockUI(), session_id="sub-compact")
        sub._chat_history = [
            {"role": "user", "content": "long conversation"},
            {"role": "assistant", "content": "many responses"},
            {"role": "user", "content": "more"},
            {"role": "assistant", "content": "even more"},
        ]
        sub.flush(sub.chat_history, compact=False)

        # Compact
        compacted = [{"role": "user", "content": "summary"}]
        sub.compact_in_place(compacted)

        sub_store = SessionStore(_history_dir(test_dir), agent_name="sub-compact")
        context = sub_store.read_context()
        assert len(context) == 1
        assert context[0]["content"] == "summary"
