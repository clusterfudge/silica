"""Tests for plan state injection timing in the agent loop.

These tests verify that plan state reminders are only injected when:
1. Assistant responds WITHOUT tool_use blocks
2. There's an active plan in executing state with incomplete tasks
3. The agent is NOT a subagent
"""

from unittest.mock import Mock, patch

from silica.developer.agent_loop import _should_inject_plan_reminder


# Patch at the source module where the functions are defined
PLANNING_MODULE = "silica.developer.tools.planning"


class TestShouldInjectPlanReminder:
    """Tests for the _should_inject_plan_reminder helper function."""

    def test_no_injection_for_subagent(self):
        """Subagents should never get plan reminders."""
        mock_context = Mock()
        mock_context.parent_session_id = "parent-123"  # This is a subagent

        should_inject, plan_state = _should_inject_plan_reminder(mock_context)

        assert should_inject is False
        assert plan_state is None

    def test_no_injection_when_no_active_plan(self):
        """No injection when there's no active plan."""
        mock_context = Mock()
        mock_context.parent_session_id = None  # Top-level agent

        with patch(f"{PLANNING_MODULE}.get_active_plan_status") as mock_status:
            mock_status.return_value = None

            should_inject, plan_state = _should_inject_plan_reminder(mock_context)

            assert should_inject is False
            assert plan_state is None

    def test_no_injection_when_plan_not_executing(self):
        """No injection when plan is not in executing state."""
        mock_context = Mock()
        mock_context.parent_session_id = None

        with patch(f"{PLANNING_MODULE}.get_active_plan_status") as mock_status:
            mock_status.return_value = {
                "status": "planning",  # Not executing
                "incomplete_tasks": 3,
            }

            should_inject, plan_state = _should_inject_plan_reminder(mock_context)

            assert should_inject is False
            assert plan_state is None

    def test_no_injection_when_no_incomplete_tasks(self):
        """No injection when all tasks are complete."""
        mock_context = Mock()
        mock_context.parent_session_id = None

        with patch(f"{PLANNING_MODULE}.get_active_plan_status") as mock_status:
            mock_status.return_value = {
                "status": "executing",
                "incomplete_tasks": 0,  # All done
            }

            should_inject, plan_state = _should_inject_plan_reminder(mock_context)

            assert should_inject is False
            assert plan_state is None

    def test_injection_when_executing_with_incomplete_tasks(self):
        """Should inject when executing plan has incomplete tasks."""
        mock_context = Mock()
        mock_context.parent_session_id = None

        with (
            patch(f"{PLANNING_MODULE}.get_active_plan_status") as mock_status,
            patch(f"{PLANNING_MODULE}.get_ephemeral_plan_state") as mock_state,
        ):
            mock_status.return_value = {
                "status": "executing",
                "incomplete_tasks": 3,
            }
            mock_state.return_value = "Plan reminder: 3 tasks remaining..."

            should_inject, plan_state = _should_inject_plan_reminder(mock_context)

            assert should_inject is True
            assert plan_state == "Plan reminder: 3 tasks remaining..."

    def test_no_injection_when_ephemeral_state_empty(self):
        """No injection when ephemeral plan state returns empty."""
        mock_context = Mock()
        mock_context.parent_session_id = None

        with (
            patch(f"{PLANNING_MODULE}.get_active_plan_status") as mock_status,
            patch(f"{PLANNING_MODULE}.get_ephemeral_plan_state") as mock_state,
        ):
            mock_status.return_value = {
                "status": "executing",
                "incomplete_tasks": 3,
            }
            mock_state.return_value = None  # No state returned

            should_inject, plan_state = _should_inject_plan_reminder(mock_context)

            assert should_inject is False
            assert plan_state is None

    def test_handles_planning_module_exception(self):
        """Should gracefully handle exceptions from planning module."""
        mock_context = Mock()
        mock_context.parent_session_id = None

        with patch(f"{PLANNING_MODULE}.get_active_plan_status") as mock_status:
            mock_status.side_effect = Exception("Planning module error")

            should_inject, plan_state = _should_inject_plan_reminder(mock_context)

            assert should_inject is False
            assert plan_state is None


class TestPlanContinuationLoop:
    """Tests for the plan continuation loop behavior.

    These tests verify that when a plan reminder is injected, the agent loop
    correctly skips the user input prompt and continues to the API call.
    """

    def test_skip_user_input_flag_exists_in_agent_loop(self):
        """Verify the skip_user_input flag is used in agent_loop."""
        import inspect
        from silica.developer import agent_loop

        source = inspect.getsource(agent_loop.run)

        # Check that skip_user_input is defined and used
        assert "skip_user_input = False" in source
        assert "skip_user_input = True" in source
        assert "not skip_user_input" in source

    def test_skip_user_input_set_on_plan_reminder_injection(self):
        """Verify skip_user_input is set to True when plan reminder is injected."""
        import inspect
        from silica.developer import agent_loop

        source = inspect.getsource(agent_loop.run)

        # Find the plan reminder injection section
        assert "_should_inject_plan_reminder" in source

        # Verify that skip_user_input = True is set near the plan reminder injection
        # This is a structural test to ensure the fix is in place
        plan_reminder_idx = source.find("_should_inject_plan_reminder")

        # Find skip_user_input = True AFTER the plan reminder check
        # (there may be other occurrences earlier in the file for other cases like max_tokens)
        skip_set_idx = source.find("skip_user_input = True", plan_reminder_idx)

        # skip_user_input = True should come AFTER the plan reminder check
        # but BEFORE the continue statement
        assert skip_set_idx > plan_reminder_idx
        continue_after_reminder_idx = source.find("continue", skip_set_idx)
        assert continue_after_reminder_idx > skip_set_idx

    def test_skip_user_input_reset_after_use(self):
        """Verify skip_user_input is reset to False after being used."""
        import inspect
        from silica.developer import agent_loop

        source = inspect.getsource(agent_loop.run)

        # Verify that skip_user_input is reset in the elif branch
        # that handles existing user messages
        assert "skip_user_input = False" in source

        # Should appear in the context of handling existing user messages
        reset_idx = source.find("skip_user_input = False", source.find("while True"))
        assert reset_idx > 0

        # Should be in the elif block that handles user messages already in history
        elif_user_msg_idx = source.find(
            'agent_context.chat_history[-1]["role"] == "user"'
        )
        assert elif_user_msg_idx > 0


class TestPlanInjectionIntegration:
    """Integration-style tests for plan injection in the agent loop context."""

    def test_plan_state_not_in_file_mentions_function(self):
        """Verify _process_file_mentions doesn't inject plan state anymore."""
        from silica.developer.agent_loop import _process_file_mentions

        mock_context = Mock()
        mock_context.parent_session_id = None

        # Create a simple chat history with a user message containing tool_result
        chat_history = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "test-123",
                        "content": "result",
                    }
                ],
            }
        ]

        # Even with plan functions returning values, _process_file_mentions
        # should NOT inject plan state (that logic was removed)
        with (
            patch(f"{PLANNING_MODULE}.get_active_plan_status") as mock_status,
            patch(f"{PLANNING_MODULE}.get_ephemeral_plan_state") as mock_state,
        ):
            mock_status.return_value = {
                "status": "executing",
                "incomplete_tasks": 3,
            }
            mock_state.return_value = "Plan reminder..."

            result = _process_file_mentions(chat_history, mock_context)

            # The result should NOT contain plan state injection
            # (it was removed from this function)
            last_message_content = result[-1]["content"]
            content_texts = [
                block.get("text", "")
                for block in last_message_content
                if isinstance(block, dict) and block.get("type") == "text"
            ]

            assert not any("Plan reminder" in text for text in content_texts)

    def test_file_mentions_still_processed(self):
        """Verify file mentions are still processed correctly."""
        from silica.developer.agent_loop import _process_file_mentions
        import tempfile
        import os

        mock_context = Mock()

        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content")
            temp_path = f.name

        try:
            chat_history = [
                {"role": "user", "content": f"Check this file @{temp_path}"}
            ]

            result = _process_file_mentions(chat_history, mock_context)

            # File content should be inlined
            last_message_content = result[-1]["content"]
            assert isinstance(last_message_content, list)

            # Should have original text + file content
            content_texts = [
                block.get("text", "")
                for block in last_message_content
                if isinstance(block, dict)
            ]
            assert any("test content" in text for text in content_texts)
        finally:
            os.unlink(temp_path)

    def test_cache_control_still_added(self):
        """Verify cache_control is still added to last text block."""
        from silica.developer.agent_loop import _process_file_mentions

        mock_context = Mock()

        chat_history = [{"role": "user", "content": "Test message"}]

        result = _process_file_mentions(chat_history, mock_context)

        # Last content block should have cache_control
        last_message = result[-1]
        assert isinstance(last_message["content"], list)
        last_block = last_message["content"][-1]
        assert "cache_control" in last_block
        assert last_block["cache_control"] == {"type": "ephemeral"}
