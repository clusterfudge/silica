"""Tests for high-severity bugs found in session history v2 review.

Bug #15: Length-based flush counter breaks after chat_history mutations
Bug #14: Auto-migration crash leaves session unrecoverable
Bug #4:  Non-atomic context.jsonl overwrite (write-to-temp-then-rename)
Bug #2:  compaction_metadata set after flush() in rotate/compact_in_place
Bug #11: Silent JSONL corruption swallowing (no logging)
"""

import json
import logging
import os
from unittest.mock import MagicMock

import pytest

from silica.developer.context import AgentContext
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.session_store import SessionStore
from silica.developer.memory import MemoryManager


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


class MockUI:
    """Minimal UserInterface for testing."""

    def handle_system_message(self, message, markdown=True):
        pass

    def permission_callback(
        self, action, resource, sandbox_mode, action_arguments, group=None
    ):
        return True

    def permission_rendering_callback(self, action, resource, action_arguments):
        pass

    def bare(self, message):
        pass

    def display_token_count(self, *a, **kw):
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
}


@pytest.fixture
def history_dir(tmp_path):
    d = tmp_path / "history" / "test-session"
    d.mkdir(parents=True)
    return d


def _make_context(history_dir, session_id="test-session"):
    """Create a fresh AgentContext pointed at the given history dir."""
    sandbox = Sandbox(
        root_directory=str(history_dir.parent.parent),
        mode=SandboxMode.ALLOW_ALL,
        permission_check_callback=MockUI().permission_callback,
    )
    memory_dir = history_dir.parent.parent / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    memory_manager = MemoryManager(base_dir=memory_dir)

    return AgentContext(
        session_id=session_id,
        parent_session_id=None,
        model_spec=MODEL_SPEC,
        sandbox=sandbox,
        user_interface=MockUI(),
        usage=[],
        memory_manager=memory_manager,
        history_base_dir=str(history_dir.parent),
    )


def _make_base_context(history_dir, session_id="test-session"):
    """Create a base context suitable for load_session_data."""
    return _make_context(history_dir, session_id)


# ===========================================================================
# Bug #15: Length-based flush counter breaks after chat_history mutations
# ===========================================================================


class TestFlushCounterAfterMutation:
    """After removing messages from chat_history (orphan cleanup, crash
    recovery pop), _last_flushed_msg_count can exceed the new list length,
    causing subsequent new messages to silently not be flushed."""

    def test_messages_written_after_pop(self, history_dir):
        """If a message is popped from chat_history (crash recovery),
        subsequent new messages must still be flushed to history.jsonl."""
        ctx = _make_context(history_dir)

        # Add 5 messages and flush
        for i in range(5):
            role = "user" if i % 2 == 0 else "assistant"
            ctx.chat_history.append({"role": role, "content": f"msg {i}"})
        ctx.flush(ctx.chat_history)

        store = ctx._get_or_create_store()
        history_before = store.read_history()
        assert len(history_before) == 5

        # Simulate crash recovery: pop the last message
        ctx.chat_history.pop()
        assert len(ctx.chat_history) == 4
        # _last_flushed_msg_count is still 5

        # Now add a NEW message
        ctx.chat_history.append({"role": "user", "content": "new after pop"})
        assert len(ctx.chat_history) == 5

        # Flush should write the new message
        ctx.flush(ctx.chat_history)

        history_after = store.read_history()
        texts = [m.get("content") for m in history_after]
        assert (
            "new after pop" in texts
        ), f"New message after pop was not flushed. History texts: {texts}"

    def test_messages_written_after_bulk_removal(self, history_dir):
        """If multiple messages are removed (orphan cleanup), new messages
        must still be flushed."""
        ctx = _make_context(history_dir)

        # Add 10 messages and flush
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            ctx.chat_history.append({"role": role, "content": f"msg {i}"})
        ctx.flush(ctx.chat_history)
        assert ctx._last_flushed_msg_count == 10

        # Simulate orphan cleanup: remove 3 messages
        ctx._chat_history = ctx.chat_history[:7]
        assert len(ctx.chat_history) == 7
        # _last_flushed_msg_count is still 10

        # Add 2 new messages
        ctx.chat_history.append({"role": "user", "content": "post-cleanup-1"})
        ctx.chat_history.append({"role": "assistant", "content": "post-cleanup-2"})
        assert len(ctx.chat_history) == 9

        ctx.flush(ctx.chat_history)

        store = ctx._get_or_create_store()
        history = store.read_history()
        texts = [m.get("content") for m in history]
        assert (
            "post-cleanup-1" in texts
        ), f"Message after cleanup not flushed. History: {texts}"
        assert "post-cleanup-2" in texts


# ===========================================================================
# Bug #14: Auto-migration crash leaves session unrecoverable
# ===========================================================================


class TestMigrationIdempotency:
    """If auto-migration is interrupted (backup dir exists but migration
    incomplete), the session should still be recoverable."""

    def test_interrupted_migration_recoverable(self, tmp_path):
        """If .backup/ exists from interrupted migration, auto-migration
        on resume should either complete it or fall back gracefully."""
        from silica.developer.context import load_session_data

        # load_session_data builds: base / "history" / session_id
        session_dir = tmp_path / "history" / "test-session"
        session_dir.mkdir(parents=True)

        # Create a legacy root.json
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        root_data = {
            "messages": messages,
            "usage": [],
            "model": MODEL_SPEC,
            "thinking_mode": "off",
        }
        root_file = session_dir / "root.json"
        root_file.write_text(json.dumps(root_data))

        # Simulate interrupted migration: create .backup/ with root.json
        # but don't create session.json (migration didn't complete)
        backup_dir = session_dir / ".backup"
        backup_dir.mkdir()
        import shutil

        shutil.copy2(root_file, backup_dir / "root.json")
        # root.json is still in session dir (deletion hadn't happened yet)

        base_ctx = _make_context(session_dir, session_id="test-session")
        result = load_session_data(
            session_id="test-session",
            base_context=base_ctx,
            history_base_dir=tmp_path,
        )
        assert (
            result is not None
        ), "Session should be loadable after interrupted migration"
        assert len(result.chat_history) == 2

    def test_interrupted_migration_root_deleted(self, tmp_path):
        """If migration backed up and deleted root.json but crashed before
        writing session.json, the session should recover from backup."""
        from silica.developer.context import load_session_data

        session_dir = tmp_path / "history" / "test-session"
        session_dir.mkdir(parents=True)

        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        root_data = {
            "messages": messages,
            "usage": [],
            "model": MODEL_SPEC,
            "thinking_mode": "off",
        }

        # Simulate: backup exists with root.json, but root.json deleted
        # from session dir and session.json not created
        backup_dir = session_dir / ".backup"
        backup_dir.mkdir()
        (backup_dir / "root.json").write_text(json.dumps(root_data))
        # No root.json in session dir, no session.json

        base_ctx = _make_context(session_dir, session_id="test-session")
        result = load_session_data(
            session_id="test-session",
            base_context=base_ctx,
            history_base_dir=tmp_path,
        )
        assert result is not None, (
            "Session should be loadable even when migration was interrupted "
            "and root.json was deleted (backup should be used)"
        )


# ===========================================================================
# Bug #4: Non-atomic context.jsonl overwrite
# ===========================================================================


class TestAtomicWrites:
    """context.jsonl and session.json should use write-to-temp-then-rename
    to prevent truncation-on-crash data loss."""

    def test_context_survives_write_error(self, history_dir):
        """If os.replace() fails (simulating crash after temp write),
        the original context.jsonl should still be intact."""
        store = SessionStore(history_dir)

        # Write initial context
        original = [
            {"role": "user", "content": "original message"},
            {"role": "assistant", "content": "original response"},
        ]
        store.write_context(original)
        assert store.read_context() == original

        # Simulate failure during atomic replace (after temp write, before rename)
        import unittest.mock as mock

        os.replace

        def _failing_replace(src, dst):
            raise OSError("Disk full")

        with mock.patch("os.replace", _failing_replace):
            try:
                store.write_context(
                    [
                        {"role": "user", "content": "new message"},
                        {"role": "assistant", "content": "new response"},
                    ]
                )
            except OSError:
                pass

        # The original context should still be intact
        recovered = store.read_context()
        assert (
            recovered == original
        ), f"Context was corrupted. Got {recovered}, expected {original}"

    def test_session_meta_survives_write_error(self, history_dir):
        """session.json should also be atomic."""
        store = SessionStore(history_dir)

        original_meta = {
            "session_id": "test-session",
            "thinking_mode": "off",
        }
        store.write_session_meta(original_meta)
        saved = store.read_session_meta()
        assert saved["session_id"] == "test-session"

        # Simulate failure during atomic replace
        import unittest.mock as mock

        def _failing_replace(src, dst):
            raise OSError("Disk full")

        with mock.patch("os.replace", _failing_replace):
            try:
                store.write_session_meta({"session_id": "new-session"})
            except OSError:
                pass

        recovered = store.read_session_meta()
        assert recovered is not None, "session.json was corrupted by failed write"
        assert recovered["session_id"] == "test-session"

    def test_temp_file_cleaned_up_on_failure(self, history_dir):
        """Temp files should not be left behind after a failed write."""
        store = SessionStore(history_dir)
        store.write_context([{"role": "user", "content": "original"}])

        import unittest.mock as mock

        def _failing_replace(src, dst):
            raise OSError("Disk full")

        with mock.patch("os.replace", _failing_replace):
            try:
                store.write_context([{"role": "user", "content": "new"}])
            except OSError:
                pass

        # No .tmp files should remain
        tmp_files = list(history_dir.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Temp files left behind: {tmp_files}"


# ===========================================================================
# Bug #2: compaction_metadata set AFTER flush in rotate/compact_in_place
# ===========================================================================


class TestCompactionMetadataWrittenOnFlush:
    """rotate() and compact_in_place() set _compaction_metadata AFTER
    calling flush(), so the metadata is not written to session.json
    until the NEXT flush."""

    def test_rotate_writes_compaction_metadata(self, history_dir):
        """After rotate(), session.json should contain compaction metadata
        without requiring an additional flush."""
        ctx = _make_context(history_dir)

        # Add initial messages and flush
        ctx.chat_history.append({"role": "user", "content": "hello"})
        ctx.chat_history.append({"role": "assistant", "content": "hi"})
        ctx.flush(ctx.chat_history)

        # Create mock compaction metadata
        metadata = MagicMock()
        metadata.original_message_count = 10
        metadata.original_token_count = 5000
        metadata.compacted_message_count = 3
        metadata.summary_token_count = 1000
        metadata.compaction_ratio = 0.8
        metadata.archive_name = "pre-compaction-001"

        # Rotate with compaction metadata
        compacted = [
            {"role": "user", "content": "[compacted summary]"},
            {"role": "assistant", "content": "continuing..."},
        ]
        ctx.rotate("pre-compaction-001", compacted, compaction_metadata=metadata)

        # session.json should have compaction info NOW
        store = ctx._get_or_create_store()
        session_meta = store.read_session_meta()
        assert "compaction" in session_meta, (
            "compaction metadata not written to session.json after rotate(). "
            "It's set AFTER flush() returns, so it's lost until next flush."
        )
        assert session_meta["compaction"]["is_compacted"] is True
        assert session_meta["compaction"]["original_message_count"] == 10

    def test_compact_in_place_writes_compaction_metadata(self, history_dir):
        """After compact_in_place(), session.json should contain compaction
        metadata without requiring an additional flush."""
        ctx = _make_context(history_dir)

        ctx.chat_history.append({"role": "user", "content": "hello"})
        ctx.chat_history.append({"role": "assistant", "content": "hi"})
        ctx.flush(ctx.chat_history)

        metadata = MagicMock()
        metadata.original_message_count = 10
        metadata.original_token_count = 5000
        metadata.compacted_message_count = 2
        metadata.summary_token_count = 800
        metadata.compaction_ratio = 0.84
        metadata.archive_name = None

        compacted = [
            {"role": "user", "content": "[summary]"},
            {"role": "assistant", "content": "ok"},
        ]
        ctx.compact_in_place(compacted, compaction_metadata=metadata)

        store = ctx._get_or_create_store()
        session_meta = store.read_session_meta()
        assert (
            "compaction" in session_meta
        ), "compaction metadata not in session.json after compact_in_place()"


# ===========================================================================
# Bug #11: Silent JSONL corruption swallowing
# ===========================================================================


# ===========================================================================
# Bug #1: cache_control and internal keys persisted in context.jsonl
# ===========================================================================


class TestContextStripping:
    """context.jsonl should never contain cache_control markers or
    internal msg keys — they are ephemeral and re-added on each API call."""

    def test_cache_control_stripped_from_context(self, history_dir):
        """cache_control markers must not be persisted to context.jsonl."""
        ctx = _make_context(history_dir)

        # Simulate messages with cache_control (as _process_file_mentions adds)
        ctx.chat_history.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "hello",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        )
        ctx.chat_history.append({"role": "assistant", "content": "hi there"})
        ctx.flush(ctx.chat_history)

        # Read raw context.jsonl
        store = ctx._get_or_create_store()
        raw_context = store.read_context()
        for msg in raw_context:
            if isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    assert (
                        "cache_control" not in block
                    ), f"cache_control persisted in context.jsonl: {block}"

    def test_internal_keys_stripped_from_context(self, history_dir):
        """Internal keys (msg_id, etc.) must not be in context.jsonl."""
        ctx = _make_context(history_dir)

        ctx.chat_history.append({"role": "user", "content": "hello"})
        ctx.chat_history.append({"role": "assistant", "content": "hi"})
        ctx.flush(ctx.chat_history)

        store = ctx._get_or_create_store()
        raw_context = store.read_context()
        for msg in raw_context:
            for key in (
                "msg_id",
                "prev_msg_id",
                "timestamp",
                "anthropic_id",
                "request_id",
            ):
                assert (
                    key not in msg
                ), f"Internal key '{key}' persisted in context.jsonl"

    def test_stale_cache_control_stripped_on_load(self, tmp_path):
        """Sessions with cache_control baked into context.jsonl from older
        code should have them stripped on load."""
        from silica.developer.context import load_session_data

        session_dir = tmp_path / "history" / "test-session"
        session_dir.mkdir(parents=True)

        # Write v2 files with stale cache_control in context.jsonl
        store = SessionStore(session_dir)
        context_with_cache = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "hello",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {"role": "assistant", "content": "hi there"},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "followup",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {"role": "assistant", "content": "sure"},
        ]
        store.write_context(context_with_cache)
        store.write_session_meta(
            {
                "session_id": "test-session",
                "model_spec": MODEL_SPEC,
                "thinking_mode": "off",
            }
        )

        base_ctx = _make_context(session_dir, session_id="test-session")
        result = load_session_data(
            session_id="test-session",
            base_context=base_ctx,
            history_base_dir=tmp_path,
        )
        assert result is not None

        # No cache_control should survive loading
        for msg in result.chat_history:
            if isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    assert (
                        "cache_control" not in block
                    ), f"Stale cache_control survived load: {block}"

    def test_cache_control_accumulation_across_flushes(self, history_dir):
        """Even after multiple flushes, context.jsonl should have zero
        cache_control markers — they must not accumulate."""
        ctx = _make_context(history_dir)

        for i in range(5):
            ctx.chat_history.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"msg {i}",
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            )
            ctx.chat_history.append({"role": "assistant", "content": f"reply {i}"})
            ctx.flush(ctx.chat_history)

        store = ctx._get_or_create_store()
        raw_context = store.read_context()
        cache_count = 0
        for msg in raw_context:
            if isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if isinstance(block, dict) and "cache_control" in block:
                        cache_count += 1
        assert (
            cache_count == 0
        ), f"Found {cache_count} cache_control markers in context.jsonl"


# ===========================================================================
# Bug #3: Usage entries all get same msg_id
# ===========================================================================


class TestUsageMsgIdCorrelation:
    """Each usage entry should be associated with the specific assistant
    message that generated it, not just the latest msg_id."""

    def test_usage_entries_get_distinct_msg_ids(self, history_dir):
        """When multiple assistant messages are flushed, each usage
        entry should reference its own assistant's msg_id."""
        ctx = _make_context(history_dir)

        # Simulate two full request/response cycles
        ctx.chat_history.append({"role": "user", "content": "first question"})
        ctx.chat_history.append({"role": "assistant", "content": "first answer"})
        ctx.usage.append(({"input_tokens": 100, "output_tokens": 50}, MODEL_SPEC))

        ctx.chat_history.append({"role": "user", "content": "second question"})
        ctx.chat_history.append({"role": "assistant", "content": "second answer"})
        ctx.usage.append(({"input_tokens": 200, "output_tokens": 80}, MODEL_SPEC))

        ctx.flush(ctx.chat_history)

        store = ctx._get_or_create_store()
        metadata = store.read_metadata()
        assert len(metadata) == 2

        # Each usage entry should have a DIFFERENT msg_id
        msg_ids = [m.get("msg_id") for m in metadata]
        assert (
            msg_ids[0] != msg_ids[1]
        ), f"Both usage entries got the same msg_id: {msg_ids}"

        # They should correspond to the two assistant messages
        history = store.read_history()
        assistant_ids = [m["msg_id"] for m in history if m.get("role") == "assistant"]
        assert len(assistant_ids) == 2
        assert msg_ids[0] == assistant_ids[0]
        assert msg_ids[1] == assistant_ids[1]

    def test_usage_with_no_new_messages_falls_back(self, history_dir):
        """If usage entries exist but no new messages were written (e.g.
        usage flushed separately), fall back to last_msg_id."""
        ctx = _make_context(history_dir)

        # Flush messages first
        ctx.chat_history.append({"role": "user", "content": "hello"})
        ctx.chat_history.append({"role": "assistant", "content": "hi"})
        ctx.flush(ctx.chat_history)

        # Now add usage without new messages
        ctx.usage.append(({"input_tokens": 50, "output_tokens": 20}, MODEL_SPEC))
        ctx.flush(ctx.chat_history)

        store = ctx._get_or_create_store()
        metadata = store.read_metadata()
        assert len(metadata) == 1
        # Should have some msg_id (fallback to last_msg_id)
        assert metadata[0].get("msg_id") is not None


# ===========================================================================
# Bug #12: Internal keys leak to get_session_data / cron consumers
# ===========================================================================


class TestConsumerStripping:
    """get_session_data and cron dashboard should not expose internal keys."""

    def test_get_session_data_strips_internal_keys(self, tmp_path):
        """get_session_data should return messages without internal keys."""
        from silica.developer.tools.sessions import get_session_data

        session_dir = tmp_path / "history" / "test-session"
        session_dir.mkdir(parents=True)

        store = SessionStore(session_dir)
        # Write context with internal keys (as would exist on disk)
        store.write_context(
            [
                {
                    "role": "user",
                    "content": "hello",
                    "msg_id": "m_0001",
                    "prev_msg_id": None,
                    "timestamp": "2025-01-01T00:00:00Z",
                },
                {
                    "role": "assistant",
                    "content": "hi",
                    "msg_id": "m_0002",
                    "prev_msg_id": "m_0001",
                    "anthropic_id": "msg_abc123",
                    "request_id": "req_xyz",
                },
            ]
        )
        store.write_session_meta(
            {"session_id": "test-session", "model_spec": MODEL_SPEC}
        )

        result = get_session_data("test-session", history_base_dir=tmp_path)

        assert result is not None
        for msg in result["messages"]:
            for key in (
                "msg_id",
                "prev_msg_id",
                "timestamp",
                "anthropic_id",
                "request_id",
            ):
                assert (
                    key not in msg
                ), f"Internal key '{key}' leaked to get_session_data consumer"


class TestCorruptionLogging:
    """Corrupted JSONL lines should be logged, not silently swallowed."""

    def test_corrupt_lines_logged(self, history_dir, caplog):
        """When _read_jsonl encounters corrupt lines, it should log a warning."""
        store = SessionStore(history_dir)

        # Write a history file with a corrupt line
        with open(store.history_path, "w") as f:
            f.write('{"role": "user", "content": "good", "msg_id": "m_0001"}\n')
            f.write("THIS IS NOT JSON\n")
            f.write(
                '{"role": "assistant", "content": "also good", "msg_id": "m_0002"}\n'
            )

        with caplog.at_level(logging.WARNING):
            records = store.read_history()

        # Should get 2 good records
        assert len(records) == 2

        # Should have logged the corruption
        assert any(
            "corrupt" in r.message.lower()
            or "skip" in r.message.lower()
            or "malformed" in r.message.lower()
            or "parse" in r.message.lower()
            for r in caplog.records
        ), (
            f"No warning logged for corrupt JSONL line. "
            f"Log records: {[r.message for r in caplog.records]}"
        )
