"""History-specific sync integration tests."""

import json
import pytest


@pytest.mark.integration
@pytest.mark.history_sync
class TestHistorySyncSpecific:
    """History sync specific scenarios."""

    def test_history_syncs_only_target_session(
        self, history_sync_engine, create_local_files, temp_persona_dir
    ):
        """Test that history sync only syncs the target session."""
        # Create multiple sessions
        create_local_files(
            {
                "history/session-test-001/conv.json": '{"session": "001"}',
                "history/session-test-001/metadata.json": '{"id": "001"}',
                "history/session-002/conv.json": '{"session": "002"}',
                "history/session-003/conv.json": '{"session": "003"}',
            }
        )

        # Sync only session-test-001
        plan = history_sync_engine.analyze_sync_operations()

        # Should only see session-test-001 files
        uploaded_paths = [op.path for op in plan.upload]

        assert any("session-test-001" in path for path in uploaded_paths)
        assert not any("session-002" in path for path in uploaded_paths)
        assert not any("session-003" in path for path in uploaded_paths)

        history_sync_engine.execute_sync(plan, show_progress=False)

        # Verify remote only has target session
        remote_index = history_sync_engine.client.get_sync_index(
            history_sync_engine.config.namespace
        )

        assert any("session-test-001" in path for path in remote_index.files.keys())
        assert not any("session-002" in path for path in remote_index.files.keys())

    def test_multiple_sessions_independent_sync(
        self, sync_client, temp_persona_dir, clean_namespace
    ):
        """Test that multiple sessions can sync independently."""
        from silica.developer.memory.sync import SyncEngine
        from silica.developer.memory.sync_config import SyncConfig

        # Create two session directories
        session1_dir = temp_persona_dir / "history/session-alpha"
        session2_dir = temp_persona_dir / "history/session-beta"
        session1_dir.mkdir(parents=True)
        session2_dir.mkdir(parents=True)

        # Create files in each session
        (session1_dir / "data.json").write_text('{"session": "alpha"}')
        (session2_dir / "data.json").write_text('{"session": "beta"}')

        # Create separate engines for each session
        config1 = SyncConfig(
            namespace=f"{clean_namespace}/history/session-alpha",
            scan_paths=[session1_dir],
            index_file=session1_dir / ".sync-index-history.json",
            base_dir=temp_persona_dir,
        )

        config2 = SyncConfig(
            namespace=f"{clean_namespace}/history/session-beta",
            scan_paths=[session2_dir],
            index_file=session2_dir / ".sync-index-history.json",
            base_dir=temp_persona_dir,
        )

        engine1 = SyncEngine(client=sync_client, config=config1)
        engine2 = SyncEngine(client=sync_client, config=config2)

        # Sync both
        plan1 = engine1.analyze_sync_operations()
        result1 = engine1.execute_sync(plan1, show_progress=False)

        plan2 = engine2.analyze_sync_operations()
        result2 = engine2.execute_sync(plan2, show_progress=False)

        assert result1.success_rate == 100.0
        assert result2.success_rate == 100.0

        # Verify independent namespaces
        index1 = sync_client.get_sync_index(config1.namespace)
        index2 = sync_client.get_sync_index(config2.namespace)

        # Each should only have their own files
        assert "history/session-alpha/data.json" in index1.files
        assert "history/session-alpha/data.json" not in index2.files

        assert "history/session-beta/data.json" in index2.files
        assert "history/session-beta/data.json" not in index1.files

        # Verify independent indices
        assert (session1_dir / ".sync-index-history.json").exists()
        assert (session2_dir / ".sync-index-history.json").exists()

    def test_sync_conversation_history_files(
        self, history_sync_engine, create_local_files, temp_persona_dir
    ):
        """Test syncing conversation history JSON files."""
        # Create realistic conversation history
        conversation = {
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
                {"role": "user", "content": "How are you?"},
                {"role": "assistant", "content": "I'm doing well, thank you!"},
            ],
            "metadata": {"created": "2025-01-01", "turn_count": 2},
        }

        create_local_files(
            {
                "history/session-test-001/conversation.json": json.dumps(
                    conversation, indent=2
                )
            }
        )

        # Sync
        plan = history_sync_engine.analyze_sync_operations()
        result = history_sync_engine.execute_sync(plan, show_progress=False)

        assert result.success_rate == 100.0

        # Verify on remote
        remote_index = history_sync_engine.client.get_sync_index(
            history_sync_engine.config.namespace
        )

        assert "history/session-test-001/conversation.json" in remote_index.files

        # Verify can download and parse
        content, md5, last_mod, content_type, version = (
            history_sync_engine.client.read_blob(
                namespace=history_sync_engine.config.namespace,
                path="history/session-test-001/conversation.json",
            )
        )

        parsed = json.loads(content.decode())
        assert parsed["metadata"]["turn_count"] == 2
        assert len(parsed["messages"]) == 4

    def test_sync_compacted_history(self, history_sync_engine, create_local_files):
        """Test syncing compacted conversation history."""
        # Create compacted format
        compacted = {
            "summary": "Conversation about greetings",
            "key_points": ["User greeted", "Assistant responded"],
            "original_turns": 10,
            "compacted_size": "80% reduction",
        }

        create_local_files(
            {
                "history/session-test-001/compacted.json": json.dumps(
                    compacted, indent=2
                ),
                "history/session-test-001/original.json": json.dumps(
                    {"turns": list(range(10))}, indent=2
                ),
            }
        )

        # Sync
        plan = history_sync_engine.analyze_sync_operations()
        result = history_sync_engine.execute_sync(plan, show_progress=False)

        assert result.success_rate == 100.0

        # Both formats should be synced
        remote_index = history_sync_engine.client.get_sync_index(
            history_sync_engine.config.namespace
        )

        assert "history/session-test-001/compacted.json" in remote_index.files
        assert "history/session-test-001/original.json" in remote_index.files

    def test_session_metadata_preserved(
        self, history_sync_engine, create_local_files, temp_persona_dir
    ):
        """Test that session metadata files are preserved."""
        metadata = {
            "session_id": "session-test-001",
            "created_at": "2025-01-01T00:00:00Z",
            "persona": "test-persona",
            "model": "claude-3-opus-20240229",
        }

        create_local_files(
            {"history/session-test-001/metadata.json": json.dumps(metadata, indent=2)}
        )

        # Sync
        plan = history_sync_engine.analyze_sync_operations()
        result = history_sync_engine.execute_sync(plan, show_progress=False)

        assert result.success_rate == 100.0

        # Download to clean environment
        (temp_persona_dir / "history/session-test-001/metadata.json").unlink()

        plan = history_sync_engine.analyze_sync_operations()
        history_sync_engine.execute_sync(plan, show_progress=False)

        # Verify metadata preserved
        downloaded_metadata = json.loads(
            (temp_persona_dir / "history/session-test-001/metadata.json").read_text()
        )

        assert downloaded_metadata["session_id"] == "session-test-001"
        assert downloaded_metadata["model"] == "claude-3-opus-20240229"
