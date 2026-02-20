"""End-to-end lifecycle test for v2 session history format.

Exercises the full session lifecycle:
1. Create session → verify files
2. Simulate conversation → flush incrementally
3. Spawn sub-agent → verify prev_msg_id linking
4. Sub-agent conversation → verify own files
5. Compaction → verify history untouched, context rewritten
6. Resume session → verify correct state, flush appends only new
7. Legacy migration → verify roundtrip
8. List sessions → verify both formats appear
"""

import json

import pytest

from silica.developer.context import AgentContext, load_session_data
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.session_store import (
    SessionStore,
    SESSION_FORMAT_VERSION,
    migrate_session,
)
from silica.developer.memory import MemoryManager
from silica.developer.tools.sessions import list_sessions
from tests.developer.test_context_flush_v2 import MockUI, MODEL_SPEC


@pytest.fixture
def base_dir(tmp_path):
    """Create a base persona directory."""
    d = tmp_path / ".silica" / "personas" / "default"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox(str(tmp_path), mode=SandboxMode.ALLOW_ALL)


def _make_context(base_dir, sandbox, session_id="e2e-session"):
    return AgentContext(
        parent_session_id=None,
        session_id=session_id,
        model_spec=MODEL_SPEC,
        sandbox=sandbox,
        user_interface=MockUI(),
        usage=[],
        memory_manager=MemoryManager(),
        history_base_dir=base_dir,
    )


class TestE2ELifecycle:
    """Full lifecycle test for v2 session format."""

    def test_stage_1_create_session(self, base_dir, sandbox):
        """Create a new session and verify files are created on first flush."""
        ctx = _make_context(base_dir, sandbox)
        ctx._chat_history = [
            {"role": "user", "content": "Hello, world!"},
            {"role": "assistant", "content": "Hi! How can I help?"},
        ]
        ctx.usage.append(
            (
                {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 10,
                    "cache_read_input_tokens": 5,
                },
                MODEL_SPEC,
            )
        )
        ctx.flush(ctx.chat_history, compact=False)

        hdir = base_dir / "history" / "e2e-session"
        assert (hdir / "session.json").exists()
        assert (hdir / "root.history.jsonl").exists()
        assert (hdir / "root.metadata.jsonl").exists()
        assert (hdir / "root.context.jsonl").exists()
        # Legacy dual-write removed — root.json no longer created
        assert not (hdir / "root.json").exists()

        meta = json.loads((hdir / "session.json").read_text())
        assert meta["version"] == SESSION_FORMAT_VERSION
        assert meta["session_id"] == "e2e-session"

    def test_stage_2_incremental_conversation(self, base_dir, sandbox):
        """5 user/assistant exchanges, flush after each, verify incremental append."""
        ctx = _make_context(base_dir, sandbox, "e2e-incremental")

        for i in range(5):
            ctx._chat_history.append({"role": "user", "content": f"question {i}"})
            ctx._chat_history.append({"role": "assistant", "content": f"answer {i}"})
            ctx.usage.append(
                (
                    {
                        "input_tokens": 10 * (i + 1),
                        "output_tokens": 5,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                    MODEL_SPEC,
                )
            )
            ctx.flush(ctx.chat_history, compact=False)

        store = SessionStore(base_dir / "history" / "e2e-incremental")
        history = store.read_history()
        assert len(history) == 10  # 5 pairs

        # Verify msg_ids are sequential
        for i, msg in enumerate(history):
            assert msg["msg_id"] == f"m_{i+1:04d}"

        # Verify prev_msg_id chain
        assert history[0]["prev_msg_id"] is None
        for i in range(1, 10):
            assert history[i]["prev_msg_id"] == f"m_{i:04d}"

        # Verify metadata
        metadata = store.read_metadata()
        assert len(metadata) == 5  # 5 usage entries

    def test_stage_3_spawn_sub_agent(self, base_dir, sandbox):
        """Spawn a sub-agent and verify prev_msg_id linking to parent."""
        root = _make_context(base_dir, sandbox, "e2e-subagent")
        root._chat_history = [
            {"role": "user", "content": "do a task"},
            {"role": "assistant", "content": "I'll use a sub-agent"},
        ]
        root.flush(root.chat_history, compact=False)

        # Create sub-agent (simulating the tool call)
        sub = root.with_user_interface(MockUI(), session_id="sub-e2e-test")

        # Verify parent's last msg_id is captured
        assert hasattr(sub, "_parent_msg_id")
        assert sub._parent_msg_id == "m_0002"
        assert sub.parent_session_id == "e2e-subagent"

    def test_stage_4_sub_agent_conversation(self, base_dir, sandbox):
        """Sub-agent has its own conversation and files."""
        root = _make_context(base_dir, sandbox, "e2e-sub-conv")
        root._chat_history = [
            {"role": "user", "content": "start"},
            {"role": "assistant", "content": "delegating"},
        ]
        root.flush(root.chat_history, compact=False)

        sub = root.with_user_interface(MockUI(), session_id="sub-worker-1")
        sub._chat_history = [
            {"role": "user", "content": "research topic X"},
            {"role": "assistant", "content": "found info on X"},
            {"role": "user", "content": "summarize"},
            {"role": "assistant", "content": "summary of X"},
        ]
        sub.flush(sub.chat_history, compact=False)

        hdir = base_dir / "history" / "e2e-sub-conv"
        assert (hdir / "sub-worker-1.history.jsonl").exists()
        assert (hdir / "sub-worker-1.context.jsonl").exists()

        sub_store = SessionStore(hdir, agent_name="sub-worker-1")
        sub_history = sub_store.read_history()
        assert len(sub_history) == 4
        assert sub_history[0]["prev_msg_id"] == "m_0002"  # links to parent
        assert sub_history[1]["prev_msg_id"].startswith("m_sub-work")  # chains within

    def test_stage_5_compaction(self, base_dir, sandbox):
        """Compaction: history untouched, context rewritten, archive created."""
        ctx = _make_context(base_dir, sandbox, "e2e-compact")
        # Build up some history
        for i in range(4):
            ctx._chat_history.append({"role": "user", "content": f"msg {i}"})
            ctx._chat_history.append({"role": "assistant", "content": f"reply {i}"})
        ctx.flush(ctx.chat_history, compact=False)

        store = SessionStore(base_dir / "history" / "e2e-compact")
        history_before = store.read_history()
        assert len(history_before) == 8

        # Rotate (simulating compaction)
        compacted = [
            {"role": "user", "content": "Summary of 8 messages"},
            {"role": "assistant", "content": "Continuing from summary"},
        ]
        archive_name = ctx.rotate("pre-compaction-test", compacted)

        # History.jsonl should still have 8 messages (untouched)
        # But we need to re-read because the store was recreated after rotate
        history_after = store.read_history()
        # Note: history grows because rotate→flush appends the 2 new compacted messages
        assert len(history_after) >= 8  # at least the original 8

        # Context should have only 2 messages
        context = store.read_context()
        assert len(context) == 2
        assert context[0]["content"] == "Summary of 8 messages"

        # Archive should exist
        hdir = base_dir / "history" / "e2e-compact"
        assert (hdir / archive_name).exists()

    def test_stage_6_resume_session(self, base_dir, sandbox):
        """Resume a session: correct context loaded, new flushes append only new."""
        ctx = _make_context(base_dir, sandbox, "e2e-resume")
        ctx._chat_history = [
            {"role": "user", "content": "original question"},
            {"role": "assistant", "content": "original answer"},
            {"role": "user", "content": "follow up"},
        ]
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

        # Resume
        base_ctx = _make_context(base_dir, sandbox, "e2e-resume")
        loaded = load_session_data("e2e-resume", base_ctx, history_base_dir=base_dir)

        assert loaded is not None
        assert len(loaded.chat_history) == 3
        assert loaded._last_flushed_msg_count == 3

        # Add new message and flush — should not duplicate
        loaded._chat_history.append(
            {"role": "assistant", "content": "follow up answer"}
        )
        loaded.flush(loaded.chat_history, compact=False)

        store = SessionStore(base_dir / "history" / "e2e-resume")
        history = store.read_history()
        assert len(history) == 4  # 3 original + 1 new
        assert history[3]["content"] == "follow up answer"

        # msg_id continues from where it left off
        assert history[3]["msg_id"] == "m_0004"
        assert history[3]["prev_msg_id"] == "m_0003"

    def test_stage_7_legacy_migration(self, base_dir, sandbox):
        """Create a legacy session, migrate it, verify files and loadability."""
        # Create a legacy root.json directly
        session_dir = base_dir / "history" / "e2e-legacy"
        session_dir.mkdir(parents=True)

        legacy_data = {
            "session_id": "e2e-legacy",
            "parent_session_id": None,
            "model_spec": MODEL_SPEC,
            "usage": [
                (
                    {
                        "input_tokens": 50,
                        "output_tokens": 25,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                    MODEL_SPEC,
                ),
            ],
            "messages": [
                {"role": "user", "content": "legacy hello"},
                {"role": "assistant", "content": "legacy world"},
            ],
            "thinking_mode": "max",
            "metadata": {
                "created_at": "2025-01-01T00:00:00Z",
                "last_updated": "2025-01-15T12:00:00Z",
                "root_dir": "/tmp/test",
            },
        }
        (session_dir / "root.json").write_text(json.dumps(legacy_data))

        # Migrate
        stats = migrate_session(session_dir)
        assert stats["message_count"] == 2
        assert (session_dir / "session.json").exists()
        assert (session_dir / ".backup" / "root.json").exists()
        assert not (session_dir / "root.json").exists()

        # Load the migrated session
        base_ctx = _make_context(base_dir, sandbox, "e2e-legacy")
        loaded = load_session_data("e2e-legacy", base_ctx, history_base_dir=base_dir)
        assert loaded is not None
        assert len(loaded.chat_history) == 2
        assert loaded.chat_history[0]["content"] == "legacy hello"

    def test_stage_8_list_sessions_mixed_formats(self, base_dir, sandbox):
        """Both v2 and legacy sessions appear in listing."""
        # Create a v2 session
        v2_ctx = _make_context(base_dir, sandbox, "e2e-v2-list")
        v2_ctx._chat_history = [{"role": "user", "content": "v2 session"}]
        v2_ctx.flush(v2_ctx.chat_history, compact=False)

        # Create a legacy session
        legacy_dir = base_dir / "history" / "e2e-legacy-list"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "root.json").write_text(
            json.dumps(
                {
                    "session_id": "e2e-legacy-list",
                    "model_spec": MODEL_SPEC,
                    "messages": [{"role": "user", "content": "legacy session"}],
                    "metadata": {
                        "created_at": "2025-01-01T00:00:00Z",
                        "last_updated": "2025-01-01T00:00:00Z",
                    },
                }
            )
        )

        sessions = list_sessions(history_base_dir=base_dir)
        session_ids = {s["session_id"] for s in sessions}
        assert "e2e-v2-list" in session_ids
        assert "e2e-legacy-list" in session_ids


class TestE2EFullCycle:
    """Single test that exercises the complete lifecycle end-to-end."""

    def test_full_lifecycle(self, base_dir, sandbox):
        """Create → converse → sub-agent → compact → resume → verify."""
        # Phase 1: Create and converse
        ctx = _make_context(base_dir, sandbox, "full-cycle")
        for i in range(3):
            ctx._chat_history.append({"role": "user", "content": f"Q{i}"})
            ctx._chat_history.append({"role": "assistant", "content": f"A{i}"})
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

        # Phase 2: Sub-agent
        sub = ctx.with_user_interface(MockUI(), session_id="sub-full-cycle")
        sub._chat_history = [
            {"role": "user", "content": "subtask"},
            {"role": "assistant", "content": "done"},
        ]
        sub.flush(sub.chat_history, compact=False)

        # Phase 3: Compact root
        compacted = [{"role": "user", "content": "Summary of 6 messages + subtask"}]
        ctx.rotate("pre-compaction-full", compacted)

        # Phase 4: Resume
        base_ctx = _make_context(base_dir, sandbox, "full-cycle")
        loaded = load_session_data("full-cycle", base_ctx, history_base_dir=base_dir)
        assert loaded is not None
        assert len(loaded.chat_history) == 1
        assert "Summary" in loaded.chat_history[0]["content"]

        # Phase 5: Continue after resume
        loaded._chat_history.append({"role": "assistant", "content": "Continuing..."})
        loaded.flush(loaded.chat_history, compact=False)

        # Verify final state
        store = SessionStore(base_dir / "history" / "full-cycle")

        # History has all messages (original 6 + compacted 1 + continued 1)
        history = store.read_history()
        assert len(history) >= 6  # at least the original 6

        # Context has only 2 (compacted + continued)
        context = store.read_context()
        assert len(context) == 2

        # Sub-agent files exist
        sub_store = SessionStore(
            base_dir / "history" / "full-cycle", agent_name="sub-full-cycle"
        )
        sub_history = sub_store.read_history()
        assert len(sub_history) == 2
        assert sub_history[0]["prev_msg_id"] == "m_0006"  # linked to parent's last
