"""Tests for plan persistence across session resume and compaction.

Plans are stored externally from chat history in ~/.silica/personas/{persona}/plans/
so they should survive both session resume and conversation compaction.
"""

import pytest
from unittest.mock import MagicMock, patch

from silica.developer.plans import PlanManager, PlanStatus


@pytest.fixture
def temp_persona_dir(tmp_path):
    """Create a temporary persona directory structure."""
    persona_dir = tmp_path / "personas" / "test_persona"
    persona_dir.mkdir(parents=True)
    return persona_dir


@pytest.fixture
def mock_context(temp_persona_dir):
    """Create a mock context with the temp persona dir."""
    context = MagicMock()
    context.history_base_dir = temp_persona_dir
    context.session_id = "test-session-123"
    return context


class TestPlanPersistenceOnResume:
    """Tests that plans persist when resuming a session."""

    def test_plan_survives_session_resume(self, temp_persona_dir, mock_context):
        """Plans should be accessible after simulating a session resume."""
        # Create a plan in the "first session"
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Feature", "session-1")
        plan.add_task("Task 1", files=["main.py"])
        plan.add_task("Task 2", files=["test.py"])
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        original_plan_id = plan.id

        # Simulate session resume by creating a new context/manager
        # (as would happen when loading a session from disk)
        new_context = MagicMock()
        new_context.history_base_dir = temp_persona_dir
        new_context.session_id = "session-2"  # Different session

        # Create a new plan manager (simulating what happens on resume)
        new_plan_manager = PlanManager(temp_persona_dir)

        # Plan should still exist and be accessible
        resumed_plan = new_plan_manager.get_plan(original_plan_id)
        assert resumed_plan is not None
        assert resumed_plan.title == "Test Feature"
        assert resumed_plan.status == PlanStatus.IN_PROGRESS
        assert len(resumed_plan.tasks) == 2

    def test_active_plan_status_after_resume(self, temp_persona_dir, mock_context):
        """get_active_plan_status should work after session resume."""
        from silica.developer.tools.planning import get_active_plan_status

        # Create an in-progress plan
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Feature X", "session-1")
        plan.add_task("Implement feature")
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        # Simulate resume with new context
        resumed_context = MagicMock()
        resumed_context.history_base_dir = temp_persona_dir
        resumed_context.session_id = "resumed-session"

        # Should still get plan status
        status = get_active_plan_status(resumed_context)
        assert status is not None
        assert status["title"] == "Feature X"
        assert status["status"] == "executing"

    def test_plan_reminder_after_resume(self, temp_persona_dir, mock_context):
        """get_active_plan_reminder should work after session resume."""
        from silica.developer.tools.planning import get_active_plan_reminder

        # Create an in-progress plan with incomplete tasks
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Feature Y", "session-1")
        plan.add_task("Task to do", files=["file.py"])
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        # Simulate resume
        resumed_context = MagicMock()
        resumed_context.history_base_dir = temp_persona_dir

        # Should get reminder
        reminder = get_active_plan_reminder(resumed_context)
        assert reminder is not None
        assert "Feature Y" in reminder
        assert "Task to do" in reminder


class TestPlanPersistenceOnCompaction:
    """Tests that plans persist when conversation is compacted."""

    def test_plan_survives_compaction(self, temp_persona_dir, mock_context):
        """Plans should remain after conversation compaction."""
        # Create a plan
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Compaction Test", mock_context.session_id)
        plan.add_task("Task 1")
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        original_plan_id = plan.id

        # Simulate compaction by clearing chat history
        # (plans are external, so this shouldn't affect them)
        mock_context._chat_history = []

        # Plan should still exist
        plan_after = plan_manager.get_plan(original_plan_id)
        assert plan_after is not None
        assert plan_after.status == PlanStatus.IN_PROGRESS

    def test_plan_status_available_after_compaction(
        self, temp_persona_dir, mock_context
    ):
        """Plan status should be available after compaction clears history."""
        from silica.developer.tools.planning import get_active_plan_status

        # Create an in-progress plan
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Compacted Feature", mock_context.session_id)
        plan.add_task("Do something")
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        # Verify status is available
        status = get_active_plan_status(mock_context)
        assert status is not None
        assert status["title"] == "Compacted Feature"

        # Simulate compaction (clear history, but context remains)
        mock_context._chat_history = []

        # Status should still be available
        status_after = get_active_plan_status(mock_context)
        assert status_after is not None
        assert status_after["title"] == "Compacted Feature"
        assert status_after["status"] == "executing"


class TestPlanInCompactionSummary:
    """Tests that active plan info is included in compaction summary generation."""

    def test_compaction_includes_plan_context(self, temp_persona_dir, mock_context):
        """The compaction prompt should include active plan info."""
        from unittest.mock import MagicMock

        # Create an in-progress plan
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Refactor Auth", mock_context.session_id)
        plan.add_task("Update models")
        plan.add_task("Add tests")
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        # Reload to get current state
        plan = plan_manager.get_plan(plan.id)

        # Mock the anthropic client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Summary of conversation")]
        mock_response.usage = MagicMock(
            input_tokens=100, output_tokens=50, cache_read_input_tokens=0
        )
        mock_response.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_response
        mock_client.messages.count_tokens.return_value = MagicMock(input_tokens=1000)

        from silica.developer.compacter import ConversationCompacter

        compacter = ConversationCompacter(client=mock_client)

        # Set up mock context with minimal chat history
        mock_context._chat_history = [
            {"role": "user", "content": "Let's refactor auth"},
            {"role": "assistant", "content": "I'll create a plan for that."},
        ]
        mock_context.model_spec = {"title": "claude-3-sonnet-20240229"}
        mock_context.sandbox = MagicMock()
        mock_context.sandbox.get_directory_listing.return_value = []
        mock_context.memory_manager = MagicMock()
        mock_context.memory_manager.get_tree.return_value = None

        # Generate summary
        with patch(
            "silica.developer.compacter.get_model",
            return_value={
                "title": "claude-3-sonnet-20240229",
                "context_window": 200000,
                "max_tokens": 8192,
            },
        ):
            compacter.generate_summary(mock_context, "sonnet")

        # Check that the system prompt includes plan info
        call_args = mock_client.messages.create.call_args
        system_prompt = call_args.kwargs.get("system", "")

        assert "Active Plan in Progress" in system_prompt
        assert plan.id in system_prompt
        assert "Refactor Auth" in system_prompt
        assert "executing" in system_prompt


class TestPlanStorageIsolation:
    """Tests that plan storage is properly isolated from session storage."""

    def test_plans_stored_in_separate_directory(self, temp_persona_dir):
        """Plans should be stored in plans/ not history/."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Isolated Plan", "any-session")

        # Plan file should exist in plans/active/
        plan_file = temp_persona_dir / "plans" / "active" / f"{plan.id}.md"
        assert plan_file.exists()

        # Should NOT be in history/
        history_dir = temp_persona_dir / "history"
        if history_dir.exists():
            plan_files_in_history = list(history_dir.rglob(f"{plan.id}*"))
            assert len(plan_files_in_history) == 0

    def test_different_sessions_share_plans(self, temp_persona_dir):
        """Plans created in one session should be visible to another."""
        # Session 1 creates a plan
        pm1 = PlanManager(temp_persona_dir)
        plan = pm1.create_plan("Shared Plan", "session-1")
        plan_id = plan.id

        # Session 2 should see it
        pm2 = PlanManager(temp_persona_dir)
        visible_plan = pm2.get_plan(plan_id)

        assert visible_plan is not None
        assert visible_plan.title == "Shared Plan"

    def test_completed_plans_move_to_completed_directory(self, temp_persona_dir):
        """Completed plans should move from active/ to completed/."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Will Complete", "session-1")
        task = plan.add_task("Only task")
        plan_manager.update_plan(plan)

        plan_id = plan.id
        task_id = task.id

        # Progress through lifecycle
        plan_manager.submit_for_review(plan_id)
        plan_manager.approve_plan(plan_id)
        plan_manager.start_execution(plan_id)

        # Reload plan after lifecycle changes to get current state
        plan = plan_manager.get_plan(plan_id)
        assert plan.status == PlanStatus.IN_PROGRESS

        # Complete the task first (required before completing plan)
        plan.complete_task(task_id)
        plan_manager.update_plan(plan)

        # Now complete the plan
        result = plan_manager.complete_plan(plan_id, "All done!")
        assert result is True, "complete_plan should return True"

        # Should be in completed/, not active/
        active_file = temp_persona_dir / "plans" / "active" / f"{plan_id}.md"
        completed_file = temp_persona_dir / "plans" / "completed" / f"{plan_id}.md"

        assert (
            not active_file.exists()
        ), f"Plan should not exist in active dir: {active_file}"
        assert (
            completed_file.exists()
        ), f"Plan should exist in completed dir: {completed_file}"

        # Verify the plan is marked as completed
        completed_plan = plan_manager.get_plan(plan_id)
        assert completed_plan is not None
        assert completed_plan.status == PlanStatus.COMPLETED
