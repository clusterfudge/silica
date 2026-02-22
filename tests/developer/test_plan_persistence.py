"""Tests for plan persistence across session resume and compaction.

Plans are stored externally from chat history in ~/.silica/personas/{persona}/plans/
so they should survive both session resume and conversation compaction.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

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

    # Mock sandbox with root_directory for project scoping
    context.sandbox = MagicMock()
    context.sandbox.root_directory = temp_persona_dir

    # Mock usage_summary for metrics baseline tracking
    context.usage_summary = MagicMock(
        return_value={
            "total_input_tokens": 1000,
            "total_output_tokens": 500,
            "total_thinking_tokens": 100,
            "cached_tokens": 200,
            "total_cost": 0.05,
        }
    )

    return context


class TestPlanPersistenceOnResume:
    """Tests that plans persist when resuming a session."""

    def test_plan_survives_session_resume(self, temp_persona_dir, mock_context):
        """Plans should be accessible after simulating a session resume."""
        # Create a plan in the "first session"
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Feature", "session-1", root_dir=str(temp_persona_dir)
        )
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
        plan = plan_manager.create_plan(
            "Feature X", "session-1", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Implement feature")
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        # Simulate resume with new context
        resumed_context = MagicMock()
        resumed_context.history_base_dir = temp_persona_dir
        resumed_context.session_id = "resumed-session"
        resumed_context.sandbox = MagicMock()
        resumed_context.sandbox.root_directory = temp_persona_dir

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
        plan = plan_manager.create_plan(
            "Feature Y", "session-1", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task to do", files=["file.py"])
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        # Simulate resume
        resumed_context = MagicMock()
        resumed_context.history_base_dir = temp_persona_dir
        resumed_context.sandbox = MagicMock()
        resumed_context.sandbox.root_directory = temp_persona_dir

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
        plan = plan_manager.create_plan(
            "Compaction Test", mock_context.session_id, root_dir=str(temp_persona_dir)
        )
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
        plan = plan_manager.create_plan(
            "Compacted Feature", mock_context.session_id, root_dir=str(temp_persona_dir)
        )
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
        plan = plan_manager.create_plan(
            "Refactor Auth", mock_context.session_id, root_dir=str(temp_persona_dir)
        )
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
        mock_context.sandbox.root_directory = temp_persona_dir  # For plan filtering
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


class TestPlanApprovalTriggersExecution:
    """Tests that approving a plan triggers agent execution."""

    def test_plan_approve_returns_execution_prompt(self, temp_persona_dir):
        """When /plan approve succeeds, it should return an execution prompt."""
        from silica.developer.toolbox import Toolbox
        import asyncio

        # Create a plan in review state
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Feature", "session-1", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Implement feature", files=["main.py"])
        plan.add_task("Add tests", files=["test_main.py"])
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)

        plan_id = plan.id

        # Create mock context and toolbox
        mock_context = MagicMock()
        mock_context.history_base_dir = temp_persona_dir
        mock_context.session_id = "test-session"
        mock_context.sandbox = MagicMock()
        mock_context.user_interface = MagicMock()
        mock_context.user_interface.handle_system_message = MagicMock()

        toolbox = Toolbox(mock_context)

        # Invoke the /plan approve command - use new event loop to avoid 'Event loop is closed' error
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                toolbox.invoke_cli_tool("plan", f"approve {plan_id}", chat_history=[])
            )
        finally:
            loop.close()

        content, auto_add = result

        # Should return execution prompt with auto_add=True
        assert auto_add is True
        assert "approved" in content.lower() or "execute" in content.lower()
        assert plan_id in content
        assert "exit_plan_mode" in content
        assert "complete_plan_task" in content

    def test_plan_approve_context_aware(self, temp_persona_dir):
        """When /plan approve is called without ID, uses active plan."""
        from silica.developer.toolbox import Toolbox
        import asyncio

        # Create a plan in review state
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Context Test", "session-1", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Do something")
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)

        # Create mock context
        mock_context = MagicMock()
        mock_context.history_base_dir = temp_persona_dir
        mock_context.session_id = "test-session"
        mock_context.sandbox = MagicMock()
        mock_context.sandbox.root_directory = temp_persona_dir  # For plan filtering
        mock_context.user_interface = MagicMock()
        mock_context.user_interface.handle_system_message = MagicMock()

        toolbox = Toolbox(mock_context)

        # Invoke /plan approve WITHOUT specifying plan ID - use new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                toolbox.invoke_cli_tool("plan", "approve", chat_history=[])
            )
        finally:
            loop.close()

        content, auto_add = result

        # Should still work and trigger execution
        assert auto_add is True
        assert plan.id in content

    def test_exit_plan_mode_execute_provides_task_details(
        self, temp_persona_dir, mock_context
    ):
        """exit_plan_mode with action='execute' should provide task details."""
        from silica.developer.tools.planning import exit_plan_mode

        # Create and approve a plan
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Detailed Tasks", mock_context.session_id, root_dir=str(temp_persona_dir)
        )
        plan.add_task("First task", files=["file1.py"], details="Do this first")
        plan.add_task("Second task", files=["file2.py"])
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)

        # Execute
        result = exit_plan_mode(mock_context, plan.id, "execute")

        # Should include task IDs, descriptions, and files
        assert "Execution Started" in result
        assert "First task" in result
        assert "file1.py" in result
        assert "complete_plan_task" in result
        assert plan.id in result


class TestEphemeralPlanStateInjection:
    """Tests for ephemeral plan state injection into messages."""

    def test_get_ephemeral_plan_state_no_plan(self, temp_persona_dir, mock_context):
        """No state returned when no plan is in progress."""
        from silica.developer.tools.planning import get_ephemeral_plan_state

        state = get_ephemeral_plan_state(mock_context)
        assert state is None

    def test_get_ephemeral_plan_state_draft_plan(self, temp_persona_dir, mock_context):
        """No state returned for draft plans (not in execution)."""
        from silica.developer.tools.planning import get_ephemeral_plan_state

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Draft Plan", mock_context.session_id, root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task 1")
        plan_manager.update_plan(plan)

        state = get_ephemeral_plan_state(mock_context)
        assert state is None  # Only IN_PROGRESS plans show state

    def test_get_ephemeral_plan_state_in_progress(self, temp_persona_dir, mock_context):
        """State returned for in-progress plans."""
        from silica.developer.tools.planning import get_ephemeral_plan_state

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Active Plan", mock_context.session_id, root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task 1", files=["file1.py"])
        plan.add_task("Task 2", files=["file2.py"])
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        state = get_ephemeral_plan_state(mock_context)

        assert state is not None
        assert "<current_plan_state>" in state
        assert "Active Plan" in state
        assert plan.id in state
        assert "Task 1" in state
        # New format shows Ready Tasks section instead of files inline
        assert "Ready Tasks" in state
        assert "Workflow:" in state  # Shows workflow hint

    def test_ephemeral_state_shows_verification_progress(
        self, temp_persona_dir, mock_context
    ):
        """State shows both completion and verification progress."""
        from silica.developer.tools.planning import get_ephemeral_plan_state

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Progress Plan", mock_context.session_id, root_dir=str(temp_persona_dir)
        )
        task1 = plan.add_task("Task 1")
        task2 = plan.add_task("Task 2")
        task3 = plan.add_task("Task 3")

        # Complete and verify task 1
        plan.complete_task(task1.id)
        plan.verify_task(task1.id, "Tests pass")

        # Only complete task 2
        plan.complete_task(task2.id)

        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        state = get_ephemeral_plan_state(mock_context)

        assert "1✓/3 verified" in state  # 1 verified
        assert "2/3 completed" in state  # 2 completed
        # New format shows Ready Tasks section with incomplete tasks
        assert "Ready Tasks" in state
        assert "Task 3" in state  # The one incomplete task should be shown
        assert task3.id in state  # Task ID should be present

    def test_ephemeral_state_all_verified_ready(self, temp_persona_dir, mock_context):
        """State shows ready message when all tasks verified."""
        from silica.developer.tools.planning import get_ephemeral_plan_state

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Done Plan", mock_context.session_id, root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Only Task")
        plan.complete_task(task.id)
        plan.verify_task(task.id, "All tests pass")
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        state = get_ephemeral_plan_state(mock_context)

        assert "Ready:" in state
        assert "complete_plan" in state


class TestPlanStorageIsolation:
    """Tests that plan storage is properly isolated from session storage."""

    def test_plans_stored_in_separate_directory(self, temp_persona_dir):
        """Plans should be stored in plans/ not history/."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Isolated Plan", "any-session", root_dir=str(temp_persona_dir)
        )

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
        plan = plan_manager.create_plan(
            "Will Complete", "session-1", root_dir=str(temp_persona_dir)
        )
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

        assert not active_file.exists(), (
            f"Plan should not exist in active dir: {active_file}"
        )
        assert completed_file.exists(), (
            f"Plan should exist in completed dir: {completed_file}"
        )

        # Verify the plan is marked as completed
        completed_plan = plan_manager.get_plan(plan_id)
        assert completed_plan is not None
        assert completed_plan.status == PlanStatus.COMPLETED


class TestSessionScopedActivePlan:
    """Tests that active_plan_id is properly scoped to sessions."""

    def test_enter_plan_mode_sets_active_plan_id(self, temp_persona_dir, mock_context):
        """enter_plan_mode should set context.active_plan_id."""
        from silica.developer.tools.planning import enter_plan_mode

        result = enter_plan_mode(mock_context, "Test Feature", "Testing")

        assert mock_context.active_plan_id is not None
        assert "Plan Mode Activated" in result
        # Verify the plan was actually created
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.get_plan(mock_context.active_plan_id)
        assert plan is not None
        assert plan.title == "Test Feature"

    def test_complete_plan_clears_active_plan_id(self, temp_persona_dir, mock_context):
        """complete_plan should clear context.active_plan_id."""
        from silica.developer.tools.planning import complete_plan

        # Create and execute a plan with verified tasks
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Do something")
        task.completed = True
        task.verified = True
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        # Set active plan
        mock_context.active_plan_id = plan.id

        # Complete the plan
        result = complete_plan(mock_context, plan.id)

        assert "Plan Completed" in result
        assert mock_context.active_plan_id is None

    def test_abandon_plan_clears_active_plan_id(self, temp_persona_dir, mock_context):
        """exit_plan_mode with action='abandon' should clear context.active_plan_id."""
        from silica.developer.tools.planning import exit_plan_mode

        # Create a plan
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )

        # Set active plan
        mock_context.active_plan_id = plan.id

        # Abandon the plan
        result = exit_plan_mode(mock_context, plan.id, action="abandon")

        assert "Plan Abandoned" in result
        assert mock_context.active_plan_id is None

    def test_get_active_plan_status_uses_session_plan(
        self, temp_persona_dir, mock_context
    ):
        """get_active_plan_status should prefer context.active_plan_id over project scan."""
        from silica.developer.tools.planning import get_active_plan_status

        plan_manager = PlanManager(temp_persona_dir)

        # Create two plans for the same project
        plan1 = plan_manager.create_plan(
            "Plan 1", "session1", root_dir=str(temp_persona_dir)
        )
        # Create another plan to verify we get the session-specific one, not most recent
        plan_manager.create_plan("Plan 2", "session2", root_dir=str(temp_persona_dir))

        # Set session-specific active plan to plan1
        mock_context.active_plan_id = plan1.id

        status = get_active_plan_status(mock_context)

        # Should return plan1, not the most recently created (plan2)
        assert status is not None
        assert status["id"] == plan1.id
        assert status["title"] == "Plan 1"

    def test_ephemeral_state_uses_session_plan(self, temp_persona_dir, mock_context):
        """get_ephemeral_plan_state should use context.active_plan_id when set."""
        from silica.developer.tools.planning import get_ephemeral_plan_state

        plan_manager = PlanManager(temp_persona_dir)

        # Create two in-progress plans
        plan1 = plan_manager.create_plan(
            "Session Plan", "session1", root_dir=str(temp_persona_dir)
        )
        plan1.add_task("Task 1")
        plan_manager.update_plan(plan1)
        plan_manager.submit_for_review(plan1.id)
        plan_manager.approve_plan(plan1.id)
        plan_manager.start_execution(plan1.id)

        plan2 = plan_manager.create_plan(
            "Other Plan", "session2", root_dir=str(temp_persona_dir)
        )
        plan2.add_task("Task 2")
        plan_manager.update_plan(plan2)
        plan_manager.submit_for_review(plan2.id)
        plan_manager.approve_plan(plan2.id)
        plan_manager.start_execution(plan2.id)

        # Set session-specific active plan to plan1
        mock_context.active_plan_id = plan1.id

        state = get_ephemeral_plan_state(mock_context)

        assert state is not None
        assert "Session Plan" in state
        assert "Other Plan" not in state

    def test_active_plan_id_persisted_in_session(self, temp_persona_dir):
        """active_plan_id should be saved/loaded with session."""
        from silica.developer.context import load_session_data

        # Create a plan
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Persisted Plan", "test-session", root_dir=str(temp_persona_dir)
        )

        # Create initial context with active plan
        mock_context = MagicMock()
        mock_context.session_id = "test-session"
        mock_context.history_base_dir = temp_persona_dir
        mock_context.active_plan_id = plan.id
        mock_context.sandbox = MagicMock()
        mock_context.sandbox.root_directory = temp_persona_dir
        mock_context.sandbox.get_directory_listing = MagicMock(return_value=[])
        mock_context._chat_history = []
        mock_context._tool_result_buffer = []
        mock_context.model_spec = {"title": "claude-3-sonnet"}
        mock_context.usage = []
        mock_context.cli_args = None
        mock_context.thinking_mode = "off"
        mock_context.parent_session_id = None

        # Create actual AgentContext and flush
        # Manually write session file with active_plan_id
        import json
        from datetime import datetime

        history_dir = temp_persona_dir / "history" / "test-session"
        history_dir.mkdir(parents=True, exist_ok=True)
        session_file = history_dir / "root.json"
        session_data = {
            "session_id": "test-session",
            "parent_session_id": None,
            "model_spec": {"title": "claude-3-sonnet"},
            "usage": [],
            "messages": [{"role": "user", "content": "test"}],
            "thinking_mode": "off",
            "active_plan_id": plan.id,
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "root_dir": str(temp_persona_dir),
                "cli_args": None,
            },
        }
        with open(session_file, "w") as f:
            json.dump(session_data, f)

        # Load the session
        base_context = MagicMock()
        base_context.sandbox = mock_context.sandbox
        base_context.user_interface = MagicMock()
        base_context.user_interface.handle_system_message = MagicMock()
        base_context.usage = []
        base_context.memory_manager = MagicMock()
        base_context.model_spec = {"title": "claude-3-sonnet"}

        loaded = load_session_data("test-session", base_context, temp_persona_dir)

        assert loaded is not None
        assert loaded.active_plan_id == plan.id


class TestPlanNewCommand:
    """Tests for /plan new command behavior."""

    def test_plan_new_prompts_for_topic(self, temp_persona_dir):
        """'/plan new' without topic should prompt user."""
        from silica.developer.toolbox import Toolbox
        import asyncio

        mock_context = MagicMock()
        mock_context.history_base_dir = temp_persona_dir
        mock_context.session_id = "test-session"
        mock_context.sandbox = MagicMock()
        mock_context.sandbox.root_directory = temp_persona_dir
        mock_context.active_plan_id = None
        mock_context.user_interface = MagicMock()
        mock_context.user_interface.handle_system_message = MagicMock()
        mock_context.user_interface.get_user_input = AsyncMock(
            return_value="New Feature"
        )

        toolbox = Toolbox(mock_context)

        # Use new event loop to avoid 'Event loop is closed' error
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                toolbox.invoke_cli_tool("plan", "new", chat_history=[])
            )
        finally:
            loop.close()

        content, auto_add = result
        assert auto_add is True
        assert "enter_plan_mode" in content
        assert "New Feature" in content

    def test_plan_new_with_topic(self, temp_persona_dir):
        """'/plan new <topic>' should use provided topic."""
        from silica.developer.toolbox import Toolbox
        import asyncio

        mock_context = MagicMock()
        mock_context.history_base_dir = temp_persona_dir
        mock_context.session_id = "test-session"
        mock_context.sandbox = MagicMock()
        mock_context.sandbox.root_directory = temp_persona_dir
        mock_context.active_plan_id = None
        mock_context.user_interface = MagicMock()
        mock_context.user_interface.handle_system_message = MagicMock()

        toolbox = Toolbox(mock_context)

        # Use new event loop to avoid 'Event loop is closed' error
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                toolbox.invoke_cli_tool("plan", "new My Feature", chat_history=[])
            )
        finally:
            loop.close()

        content, auto_add = result
        assert auto_add is True
        assert "My Feature" in content


class TestPlanContextAwareBehavior:
    """Tests for context-aware /plan behavior."""

    def test_plan_no_args_views_active_plan(self, temp_persona_dir):
        """'/plan' with active plan should view it."""
        from silica.developer.toolbox import Toolbox
        import asyncio

        # Create a plan
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Active Plan", "session", root_dir=str(temp_persona_dir)
        )

        mock_context = MagicMock()
        mock_context.history_base_dir = temp_persona_dir
        mock_context.session_id = "test-session"
        mock_context.sandbox = MagicMock()
        mock_context.sandbox.root_directory = temp_persona_dir
        mock_context.active_plan_id = plan.id
        mock_context.user_interface = MagicMock()
        mock_context.user_interface.handle_system_message = MagicMock()

        toolbox = Toolbox(mock_context)

        # Use new event loop to avoid 'Event loop is closed' error
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                toolbox.invoke_cli_tool("plan", "", chat_history=[])
            )
        finally:
            loop.close()

        # Should return empty string or ("", False) tuple (view result printed directly)
        assert result == "" or result == ("", False)
        # Should have called handle_system_message with plan markdown
        calls = mock_context.user_interface.handle_system_message.call_args_list
        assert any("Active Plan" in str(call) for call in calls)

    def test_plan_no_args_creates_new_if_no_active(self, temp_persona_dir):
        """'/plan' without active plan should prompt to create new."""
        from silica.developer.toolbox import Toolbox
        import asyncio

        mock_context = MagicMock()
        mock_context.history_base_dir = temp_persona_dir
        mock_context.session_id = "test-session"
        mock_context.sandbox = MagicMock()
        mock_context.sandbox.root_directory = temp_persona_dir
        mock_context.active_plan_id = None
        mock_context.user_interface = MagicMock()
        mock_context.user_interface.handle_system_message = MagicMock()
        mock_context.user_interface.get_user_input = AsyncMock(
            return_value="New Plan Topic"
        )

        toolbox = Toolbox(mock_context)

        # Use new event loop to avoid 'Event loop is closed' error
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                toolbox.invoke_cli_tool("plan", "", chat_history=[])
            )
        finally:
            loop.close()

        content, auto_add = result
        assert auto_add is True
        assert "enter_plan_mode" in content
        assert "New Plan Topic" in content
