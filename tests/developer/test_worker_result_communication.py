"""Tests for worker result communication fixes.

Verifies that:
1. Worker CLI sends results to coordinator's inbox (direct) not broadcast (room)
2. Worker CLI captures agent's last response as summary
3. Subscribe cursors use context cursors (not stale session attributes)
"""

import pytest


class TestExtractLastAssistantText:
    """Test the _extract_last_assistant_text helper."""

    def test_extracts_string_content(self):
        from silica.developer.cli.worker import _extract_last_assistant_text

        history = [
            {"role": "user", "content": "Do something"},
            {"role": "assistant", "content": "I did the thing. Here are results."},
        ]
        result = _extract_last_assistant_text(history)
        assert result == "I did the thing. Here are results."

    def test_extracts_content_blocks(self):
        from silica.developer.cli.worker import _extract_last_assistant_text

        history = [
            {"role": "user", "content": "Do something"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Part 1"},
                    {"type": "tool_use", "id": "x", "name": "foo", "input": {}},
                    {"type": "text", "text": "Part 2"},
                ],
            },
        ]
        result = _extract_last_assistant_text(history)
        assert "Part 1" in result
        assert "Part 2" in result

    def test_skips_tool_use_only_messages(self):
        from silica.developer.cli.worker import _extract_last_assistant_text

        history = [
            {"role": "user", "content": "Do something"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "x", "name": "foo", "input": {}},
                ],
            },
            {"role": "user", "content": "tool result"},
            {"role": "assistant", "content": "Final answer here"},
        ]
        result = _extract_last_assistant_text(history)
        assert result == "Final answer here"

    def test_truncates_long_text(self):
        from silica.developer.cli.worker import _extract_last_assistant_text

        history = [
            {"role": "assistant", "content": "x" * 3000},
        ]
        result = _extract_last_assistant_text(history)
        assert len(result) <= 2003  # 2000 + "..."
        assert result.endswith("...")

    def test_empty_history(self):
        from silica.developer.cli.worker import _extract_last_assistant_text

        assert _extract_last_assistant_text([]) == ""
        assert _extract_last_assistant_text(None) == ""

    def test_no_assistant_messages(self):
        from silica.developer.cli.worker import _extract_last_assistant_text

        history = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "Still here?"},
        ]
        assert _extract_last_assistant_text(history) == ""


class TestWorkerResultRouting:
    """Test that worker results are sent to coordinator's inbox, not broadcast."""

    def test_result_uses_send_to_coordinator_not_broadcast(self):
        """Verify the worker CLI sends Result via send_to_coordinator (direct)
        rather than broadcast (room)."""
        # Read the source to verify the pattern
        import inspect
        from silica.developer.cli import worker

        source = inspect.getsource(worker._run_worker_agent)

        # After task execution, the CLI should use send_to_coordinator for Result
        assert "coord_context.send_to_coordinator(" in source
        # Should NOT use broadcast for Result messages
        # (broadcast is fine for Idle and Progress, but not for Result)
        # Count occurrences of broadcast with Result
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "broadcast(" in line and "Result(" in line:
                pytest.fail(
                    f"Found broadcast(Result(...)) at line {i}: {line.strip()}\n"
                    "Results should use send_to_coordinator() not broadcast()"
                )

    def test_result_includes_agent_summary(self):
        """Verify the worker CLI captures the agent's last response as summary."""
        import inspect
        from silica.developer.cli import worker

        source = inspect.getsource(worker._run_worker_agent)

        # Should NOT have the hard-coded generic summary
        assert '"Task executed by worker agent"' not in source

        # Should reference _extract_last_assistant_text
        assert "_extract_last_assistant_text" in source


class TestWorkerToolAvailability:
    """Test that workers have coordination tools available."""

    def test_worker_includes_coordination_tools(self):
        """Verify the worker CLI provides WORKER_COORDINATION_TOOLS to the agent."""
        import inspect
        from silica.developer.cli import worker

        source = inspect.getsource(worker._run_worker_agent)

        # Should import WORKER_COORDINATION_TOOLS
        assert "WORKER_COORDINATION_TOOLS" in source
        # Should pass them to run() via tools parameter
        # Code may split across lines, so check both identifiers exist
        assert "ALL_TOOLS" in source
        assert "WORKER_COORDINATION_TOOLS" in source

    def test_worker_coordination_tools_include_essentials(self):
        """Verify WORKER_COORDINATION_TOOLS contains the essential tools."""
        from silica.developer.tools import WORKER_COORDINATION_TOOLS

        tool_names = [t.__name__ for t in WORKER_COORDINATION_TOOLS]
        assert "send_to_coordinator" in tool_names
        assert "mark_idle" in tool_names
        assert "check_inbox" in tool_names
        assert "broadcast_status" in tool_names


class TestSubscribeCursors:
    """Test that subscribe topics use context cursors properly."""

    def test_subscribe_topics_use_context_cursors(self):
        """Verify _wait_with_coordination reads cursors from ctx, not session."""
        import inspect
        from silica.developer import agent_loop

        source = inspect.getsource(agent_loop._wait_with_coordination)

        # Should use ctx._last_inbox_mid, not session._last_inbox_mid
        assert "ctx._last_inbox_mid" in source
        assert "ctx._last_room_mid" in source

        # Should NOT use getattr(session, "_last_inbox_mid", None)
        assert 'getattr(session, "_last_inbox_mid"' not in source
        assert 'getattr(session, "_last_room_mid"' not in source

    def test_subscribe_handler_does_not_advance_cursors(self):
        """Verify the subscribe handler doesn't advance cursors itself.

        Cursors should only be advanced by receive_messages() to avoid
        skipping messages.
        """
        import inspect
        from silica.developer import agent_loop

        source = inspect.getsource(agent_loop._wait_with_coordination)

        # The subscribe handler should NOT set session._last_inbox_mid
        # or session._last_room_mid or ctx._last_inbox_mid, etc.
        # after receiving events
        assert "session._last_inbox_mid = " not in source
        assert "session._last_room_mid = " not in source

    def test_subscribe_refreshes_topics_on_resubscribe(self):
        """Verify topics dict is refreshed from context on each subscribe loop."""
        import inspect
        from silica.developer import agent_loop

        source = inspect.getsource(agent_loop._wait_with_coordination)

        # Inside _subscribe_for_messages, topics should be refreshed
        # Look for the pattern of updating topics from ctx cursors in the while loop
        assert "topics[inbox_topic] = ctx._last_inbox_mid" in source
