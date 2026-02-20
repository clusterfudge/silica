"""Tests for legacy session migration to v2 format."""

import json
from pathlib import Path

import pytest

from silica.developer.session_store import (
    SessionStore,
    SESSION_FORMAT_VERSION,
    migrate_session,
    migrate_all_sessions,
)


@pytest.fixture
def session_dir(tmp_path):
    d = tmp_path / "test-session"
    d.mkdir()
    return d


def _write_legacy_root(session_dir, messages=None, usage=None, extras=None):
    """Create a legacy root.json file."""
    if messages is None:
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "user", "content": "bye"},
            {"role": "assistant", "content": "goodbye"},
        ]
    if usage is None:
        usage = [
            (
                {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                {
                    "title": "claude-sonnet-4-20250514",
                    "pricing": {"input": 3.0, "output": 15.0},
                    "cache_pricing": {"write": 3.75, "read": 0.3},
                    "max_tokens": 8192,
                },
            ),
            (
                {
                    "input_tokens": 200,
                    "output_tokens": 75,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                {
                    "title": "claude-sonnet-4-20250514",
                    "pricing": {"input": 3.0, "output": 15.0},
                    "cache_pricing": {"write": 3.75, "read": 0.3},
                    "max_tokens": 8192,
                },
            ),
        ]
    data = {
        "session_id": session_dir.name,
        "parent_session_id": None,
        "model_spec": {"title": "claude-sonnet-4-20250514"},
        "usage": usage,
        "messages": messages,
        "thinking_mode": "max",
        "active_plan_id": None,
        "metadata": {
            "created_at": "2025-06-15T10:00:00Z",
            "last_updated": "2025-06-15T11:00:00Z",
            "root_dir": "/home/user/project",
            "cli_args": ["--verbose"],
        },
    }
    if extras:
        data.update(extras)
    (session_dir / "root.json").write_text(json.dumps(data, indent=2))
    return data


class TestMigrateSession:
    """Tests for migrate_session()."""

    def test_basic_migration(self, session_dir):
        """root.json → v2 files, originals backed up."""
        _write_legacy_root(session_dir)
        stats = migrate_session(session_dir)

        assert stats["message_count"] == 4
        assert stats["usage_count"] == 2
        assert (session_dir / "session.json").exists()
        assert (session_dir / "root.history.jsonl").exists()
        assert (session_dir / "root.metadata.jsonl").exists()
        assert (session_dir / "root.context.jsonl").exists()
        # Original removed from session dir, safe in .backup
        assert not (session_dir / "root.json").exists()
        assert (session_dir / ".backup" / "root.json").exists()

    def test_backup_contains_all_originals(self, session_dir):
        """The .backup/ dir has exact copies of all original files."""
        _write_legacy_root(session_dir)
        original_root = (session_dir / "root.json").read_text()
        migrate_session(session_dir)

        backup_root = (session_dir / ".backup" / "root.json").read_text()
        assert backup_root == original_root

    def test_backup_prevents_double_migration(self, session_dir):
        """If .backup/ exists, migration refuses to overwrite it."""
        _write_legacy_root(session_dir)
        (session_dir / ".backup").mkdir()
        with pytest.raises(ValueError, match="Backup already exists"):
            migrate_session(session_dir)

    def test_message_count_preserved(self, session_dir):
        """history.jsonl should have same number of messages as original."""
        _write_legacy_root(session_dir)
        migrate_session(session_dir)

        store = SessionStore(session_dir)
        history = store.read_history()
        assert len(history) == 4

    def test_msg_ids_sequential(self, session_dir):
        """Messages get sequential msg_ids with prev_msg_id chain."""
        _write_legacy_root(session_dir)
        migrate_session(session_dir)

        store = SessionStore(session_dir)
        history = store.read_history()
        assert history[0]["msg_id"] == "m_0001"
        assert history[1]["msg_id"] == "m_0002"
        assert history[2]["msg_id"] == "m_0003"
        assert history[3]["msg_id"] == "m_0004"
        assert history[0]["prev_msg_id"] is None
        assert history[1]["prev_msg_id"] == "m_0001"
        assert history[2]["prev_msg_id"] == "m_0002"
        assert history[3]["prev_msg_id"] == "m_0003"

    def test_usage_paired_with_assistant_msg_ids(self, session_dir):
        """Usage entries paired with correct assistant msg_ids in metadata.jsonl."""
        _write_legacy_root(session_dir)
        migrate_session(session_dir)

        store = SessionStore(session_dir)
        metadata = store.read_metadata()
        assert len(metadata) == 2
        assert metadata[0]["msg_id"] == "m_0002"
        assert metadata[1]["msg_id"] == "m_0004"
        assert metadata[0]["usage"]["input_tokens"] == 100
        assert metadata[1]["usage"]["input_tokens"] == 200

    def test_session_json_version_and_fields(self, session_dir):
        """session.json has version=2 and all metadata fields."""
        _write_legacy_root(session_dir)
        migrate_session(session_dir)

        store = SessionStore(session_dir)
        meta = store.read_session_meta()
        assert meta["version"] == SESSION_FORMAT_VERSION
        assert meta["session_id"] == session_dir.name
        assert meta["thinking_mode"] == "max"
        assert meta["root_dir"] == "/home/user/project"
        assert meta["cli_args"] == ["--verbose"]
        assert meta["migrated_from"] == "root.json"

    def test_context_matches_messages(self, session_dir):
        """root.context.jsonl matches history messages."""
        _write_legacy_root(session_dir)
        migrate_session(session_dir)

        store = SessionStore(session_dir)
        context = store.read_context()
        assert len(context) == 4
        assert context[0]["content"] == "hello"

    def test_idempotency(self, session_dir):
        """Running migration twice is safe (second raises ValueError)."""
        _write_legacy_root(session_dir)
        migrate_session(session_dir)

        with pytest.raises(ValueError, match="already in v2 format"):
            migrate_session(session_dir)

    def test_dry_run(self, session_dir):
        """Dry-run mode: original untouched, preview dir has output."""
        _write_legacy_root(session_dir)
        stats = migrate_session(session_dir, dry_run=True)

        assert stats["dry_run"] is True
        assert "session.json" in stats["files_created"]
        # Original files should NOT be modified
        assert not (session_dir / "session.json").exists()
        assert (session_dir / "root.json").exists()

        # Preview directory should have the migrated files
        preview = Path(stats["preview_dir"])
        assert preview.exists()
        assert (preview / "session.json").exists()
        assert (preview / "root.history.jsonl").exists()
        assert (preview / "root.context.jsonl").exists()
        # Original backed up in preview
        assert (preview / ".backup" / "root.json").exists()

    def test_dry_run_with_explicit_preview_dir(self, session_dir, tmp_path):
        """Dry-run writes to a caller-specified preview directory."""
        _write_legacy_root(session_dir)
        preview = tmp_path / "my-preview"
        stats = migrate_session(session_dir, dry_run=True, preview_dir=preview)

        assert stats["preview_dir"] == str(preview / session_dir.name)
        assert (preview / session_dir.name / "session.json").exists()

    def test_dry_run_compacted_session_preview(self, session_dir):
        """Dry-run on compacted session shows archive merge in preview."""
        original_messages = [{"role": "user", "content": f"q{i}"} for i in range(5)]
        archive = {"messages": original_messages}
        (session_dir / "pre-compaction-20250601_100000.json").write_text(
            json.dumps(archive)
        )
        _write_legacy_root(
            session_dir,
            messages=[
                {"role": "user", "content": "summary"},
                {"role": "assistant", "content": "ok"},
            ],
            extras={"compaction": {"is_compacted": True}},
        )

        stats = migrate_session(session_dir, dry_run=True)
        preview = Path(stats["preview_dir"])

        store = SessionStore(preview)
        history = store.read_history()
        assert len(history) == 7  # 5 from archive + 2 from root

    def test_nonexistent_root_json_raises(self, session_dir):
        with pytest.raises(FileNotFoundError):
            migrate_session(session_dir)

    def test_pre_compaction_archives_in_backup(self, session_dir):
        """pre-compaction archives are backed up and removed."""
        _write_legacy_root(session_dir)
        archive_data = {
            "messages": [
                {"role": "user", "content": "old1"},
                {"role": "assistant", "content": "old2"},
            ],
            "metadata": {"created_at": "2025-01-01T00:00:00Z"},
        }
        (session_dir / "pre-compaction-20250615_100000.json").write_text(
            json.dumps(archive_data)
        )

        migrate_session(session_dir)

        # Original removed, backup has it
        assert not (session_dir / "pre-compaction-20250615_100000.json").exists()
        assert (
            session_dir / ".backup" / "pre-compaction-20250615_100000.json"
        ).exists()

    def test_sub_agent_files_migrated(self, session_dir):
        """Sub-agent *.json → *.history.jsonl + *.context.jsonl, original backed up."""
        _write_legacy_root(session_dir)
        sub_data = {
            "session_id": "sub-abc123",
            "messages": [
                {"role": "user", "content": "subtask"},
                {"role": "assistant", "content": "done"},
            ],
        }
        (session_dir / "sub-abc123.json").write_text(json.dumps(sub_data))

        migrate_session(session_dir)

        assert (session_dir / "sub-abc123.history.jsonl").exists()
        assert (session_dir / "sub-abc123.context.jsonl").exists()
        # Original removed, backup has it
        assert not (session_dir / "sub-abc123.json").exists()
        assert (session_dir / ".backup" / "sub-abc123.json").exists()

    def test_preserves_compaction_info(self, session_dir):
        """Compaction metadata from root.json preserved in session.json."""
        _write_legacy_root(
            session_dir,
            extras={
                "compaction": {
                    "is_compacted": True,
                    "original_message_count": 100,
                    "compacted_message_count": 10,
                }
            },
        )
        migrate_session(session_dir)

        store = SessionStore(session_dir)
        meta = store.read_session_meta()
        assert meta["compaction"]["is_compacted"] is True
        assert meta["compaction"]["original_message_count"] == 100

    def test_compacted_session_no_duplicate_messages(self, session_dir):
        """Compacted sessions: history has archives + current, no duplicates."""
        original_messages = []
        for i in range(10):
            original_messages.append({"role": "user", "content": f"orig_q{i}"})
            original_messages.append({"role": "assistant", "content": f"orig_a{i}"})

        archive_data = {
            "messages": original_messages,
            "metadata": {"created_at": "2025-06-01T00:00:00Z"},
        }
        (session_dir / "pre-compaction-20250615_100000.json").write_text(
            json.dumps(archive_data)
        )

        compacted_messages = [
            {"role": "user", "content": "Summary of 20 original messages"},
            {"role": "assistant", "content": "Understood, continuing from summary"},
            {"role": "user", "content": "new question after compaction"},
            {"role": "assistant", "content": "new answer after compaction"},
        ]
        _write_legacy_root(
            session_dir,
            messages=compacted_messages,
            extras={
                "compaction": {
                    "is_compacted": True,
                    "original_message_count": 20,
                    "compacted_message_count": 2,
                }
            },
        )

        stats = migrate_session(session_dir)
        assert stats["is_compacted"] is True
        assert stats["archive_count"] == 1

        store = SessionStore(session_dir)
        history = store.read_history()
        assert len(history) == 24

        assert history[0]["content"] == "orig_q0"
        assert history[19]["content"] == "orig_a9"
        assert history[20]["content"] == "Summary of 20 original messages"
        assert history[23]["content"] == "new answer after compaction"

        assert history[19]["msg_id"] == "m_0020"
        assert history[20]["msg_id"] == "m_0021"
        assert history[20]["prev_msg_id"] == "m_0020"

        context = store.read_context()
        assert len(context) == 4
        assert context[0]["content"] == "Summary of 20 original messages"

    def test_multiple_compaction_archives(self, session_dir):
        """Multiple compaction rounds: all archives incorporated in order."""
        archive1 = {
            "messages": [
                {"role": "user", "content": "round1_q"},
                {"role": "assistant", "content": "round1_a"},
            ]
        }
        (session_dir / "pre-compaction-20250601_100000.json").write_text(
            json.dumps(archive1)
        )

        archive2 = {
            "messages": [
                {"role": "user", "content": "round2_q"},
                {"role": "assistant", "content": "round2_a"},
            ]
        }
        (session_dir / "pre-compaction-20250610_100000.json").write_text(
            json.dumps(archive2)
        )

        _write_legacy_root(
            session_dir,
            messages=[
                {"role": "user", "content": "final_summary"},
                {"role": "assistant", "content": "continuing"},
            ],
            extras={"compaction": {"is_compacted": True}},
        )

        stats = migrate_session(session_dir)
        assert stats["archive_count"] == 2

        store = SessionStore(session_dir)
        history = store.read_history()

        assert len(history) == 6
        assert history[0]["content"] == "round1_q"
        assert history[2]["content"] == "round2_q"
        assert history[4]["content"] == "final_summary"

        for i, msg in enumerate(history):
            assert msg["msg_id"] == f"m_{i + 1:04d}"

    def test_rollback_from_backup(self, session_dir):
        """After migration, .backup/ can restore the original state."""
        _write_legacy_root(session_dir)
        original_root = (session_dir / "root.json").read_text()

        migrate_session(session_dir)

        # Verify v2 state
        assert (session_dir / "session.json").exists()
        assert not (session_dir / "root.json").exists()

        # Simulate rollback: remove v2 files, restore from backup
        import shutil

        for f in session_dir.iterdir():
            if f.name == ".backup":
                continue
            f.unlink()
        for f in (session_dir / ".backup").iterdir():
            shutil.copy2(f, session_dir / f.name)
        shutil.rmtree(session_dir / ".backup")

        # Original state restored
        assert (session_dir / "root.json").exists()
        assert (session_dir / "root.json").read_text() == original_root
        assert not (session_dir / "session.json").exists()


class TestMigrateAllSessions:
    """Tests for migrate_all_sessions()."""

    def test_bulk_migration(self, tmp_path):
        """Migrate multiple sessions."""
        base = tmp_path / "personas" / "default"
        history_dir = base / "history"

        for name in ["sess-1", "sess-2", "sess-3"]:
            d = history_dir / name
            d.mkdir(parents=True)
            _write_legacy_root(d)

        results = migrate_all_sessions(base)
        assert len(results) == 3
        for r in results:
            assert r["status"] == "ok"
            assert r["message_count"] == 4
            # Each has a backup
            sd = Path(r["session_dir"])
            assert (sd / ".backup" / "root.json").exists()

    def test_skips_already_migrated(self, tmp_path):
        """Already-migrated sessions are skipped."""
        base = tmp_path / "personas" / "default"
        history_dir = base / "history"

        d1 = history_dir / "legacy-sess"
        d1.mkdir(parents=True)
        _write_legacy_root(d1)

        d2 = history_dir / "v2-sess"
        d2.mkdir(parents=True)
        (d2 / "session.json").write_text('{"version": 2}')
        (d2 / "root.json").write_text("{}")

        results = migrate_all_sessions(base)
        assert len(results) == 1

    def test_progress_callback(self, tmp_path):
        base = tmp_path / "personas" / "default"
        history_dir = base / "history"
        d = history_dir / "sess-1"
        d.mkdir(parents=True)
        _write_legacy_root(d)

        calls = []
        migrate_all_sessions(
            base, progress_callback=lambda sd, i, t: calls.append((i, t))
        )
        assert len(calls) == 1
        assert calls[0] == (0, 1)

    def test_rollback_script_generated(self, tmp_path):
        """Real migration generates a rollback script."""
        base = tmp_path / "personas" / "default"
        history_dir = base / "history"
        d = history_dir / "sess-1"
        d.mkdir(parents=True)
        _write_legacy_root(d)

        # Ensure ~/.silica exists for the script
        silica_dir = Path.home() / ".silica"
        silica_dir.mkdir(exist_ok=True)

        migrate_all_sessions(base)

        script = Path.home() / ".silica" / "rollback-v2-migration.sh"
        assert script.exists()
        content = script.read_text()
        assert "rollback_session" in content
        assert str(d) in content


class TestMigratedSessionLoadable:
    """Test that migrated sessions can be loaded via load_session_data()."""

    def test_load_after_migration(self, tmp_path):
        from silica.developer.context import load_session_data, AgentContext
        from silica.developer.sandbox import Sandbox, SandboxMode
        from silica.developer.memory import MemoryManager

        base = tmp_path / "personas" / "default"
        session_dir = base / "history" / "migrated-sess"
        session_dir.mkdir(parents=True)
        _write_legacy_root(session_dir)

        migrate_session(session_dir)

        from tests.developer.test_context_flush_v2 import MockUI, MODEL_SPEC

        base_ctx = AgentContext(
            parent_session_id=None,
            session_id="migrated-sess",
            model_spec=MODEL_SPEC,
            sandbox=Sandbox(str(tmp_path), mode=SandboxMode.ALLOW_ALL),
            user_interface=MockUI(),
            usage=[],
            memory_manager=MemoryManager(),
            history_base_dir=base,
        )

        loaded = load_session_data("migrated-sess", base_ctx, history_base_dir=base)
        assert loaded is not None
        assert len(loaded.chat_history) == 4
        assert loaded.chat_history[0]["content"] == "hello"
