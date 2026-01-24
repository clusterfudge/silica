"""Tests for the planning tools."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from silica.developer.plans import PlanManager, PlanStatus
from silica.developer.tools.planning import (
    enter_plan_mode,
    update_plan,
    add_plan_tasks,
    read_plan,
    list_plans,
    exit_plan_mode,
    complete_plan_task,
    complete_plan,
    reopen_plan,
    _get_plan_manager,
)


@pytest.fixture
def temp_persona_dir(tmp_path):
    """Create a temporary persona directory."""
    persona_dir = tmp_path / "personas" / "test"
    persona_dir.mkdir(parents=True)
    return persona_dir


@pytest.fixture
def mock_context(temp_persona_dir):
    """Create a mock AgentContext."""
    context = MagicMock()
    context.session_id = "test-session-123"
    context.history_base_dir = temp_persona_dir

    # Mock sandbox with root_directory for project scoping
    context.sandbox = MagicMock()
    context.sandbox.root_directory = temp_persona_dir

    # Mock user_interface for ask_clarifications
    context.user_interface = MagicMock()
    context.user_interface.get_user_choice = AsyncMock(return_value="Option A")
    context.user_interface.get_user_input = AsyncMock(return_value="user input")

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


class TestEnterPlanMode:
    """Tests for enter_plan_mode tool."""

    def test_enter_plan_mode_creates_plan(self, mock_context, temp_persona_dir):
        result = enter_plan_mode(
            mock_context,
            topic="Implement new feature",
            reason="Complex multi-file change",
        )

        assert "Plan Mode Activated" in result
        assert "Plan ID:" in result

        # Verify plan was created
        plan_manager = PlanManager(temp_persona_dir)
        plans = plan_manager.list_active_plans()
        assert len(plans) == 1
        assert plans[0].title == "Implement new feature"

    def test_enter_plan_mode_without_reason(self, mock_context, temp_persona_dir):
        result = enter_plan_mode(
            mock_context,
            topic="Quick fix",
        )

        assert "Plan Mode Activated" in result

        plan_manager = PlanManager(temp_persona_dir)
        plans = plan_manager.list_active_plans()
        assert len(plans) == 1
        assert "Quick fix" in plans[0].context


class TestUpdatePlan:
    """Tests for update_plan tool."""

    def test_update_context(self, mock_context, temp_persona_dir):
        # Create a plan first
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = update_plan(
            mock_context,
            plan_id=plan.id,
            section="context",
            content="Updated context information",
        )

        assert "Updated 'context'" in result

        # Verify update
        updated = plan_manager.get_plan(plan.id)
        assert updated.context == "Updated context information"

    def test_update_approach(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = update_plan(
            mock_context,
            plan_id=plan.id,
            section="approach",
            content="We will implement in 3 phases",
        )

        assert "Updated 'approach'" in result

        updated = plan_manager.get_plan(plan.id)
        assert updated.approach == "We will implement in 3 phases"

    def test_update_considerations(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = update_plan(
            mock_context,
            plan_id=plan.id,
            section="considerations",
            content="Risks: Database migration\nDependencies: Auth service",
        )

        assert "Updated 'considerations'" in result

        updated = plan_manager.get_plan(plan.id)
        assert "Risks" in updated.considerations
        assert "Dependencies" in updated.considerations

    def test_update_nonexistent_plan(self, mock_context):
        result = update_plan(
            mock_context,
            plan_id="nonexistent",
            section="context",
            content="test",
        )

        assert "Error" in result
        assert "not found" in result

    def test_update_invalid_section(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = update_plan(
            mock_context,
            plan_id=plan.id,
            section="invalid_section",
            content="test",
        )

        assert "Error" in result
        assert "Invalid section" in result


class TestAddPlanTasks:
    """Tests for add_plan_tasks tool."""

    def test_add_single_task(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        tasks_json = json.dumps(
            [{"description": "Create database schema", "files": ["schema.sql"]}]
        )

        result = add_plan_tasks(mock_context, plan.id, tasks_json)

        assert "Added 1 tasks" in result

        updated = plan_manager.get_plan(plan.id)
        assert len(updated.tasks) == 1
        assert updated.tasks[0].description == "Create database schema"
        assert "schema.sql" in updated.tasks[0].files

    def test_add_multiple_tasks(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        tasks_json = json.dumps(
            [
                {"description": "Task 1"},
                {"description": "Task 2", "details": "More info"},
                {"description": "Task 3", "tests": "Unit tests"},
            ]
        )

        result = add_plan_tasks(mock_context, plan.id, tasks_json)

        assert "Added 3 tasks" in result

        updated = plan_manager.get_plan(plan.id)
        assert len(updated.tasks) == 3

    def test_add_tasks_with_dependencies(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        tasks_json = json.dumps(
            [
                {"description": "Setup", "files": ["setup.py"]},
                {"description": "Implementation", "dependencies": ["task-1"]},
            ]
        )

        add_plan_tasks(mock_context, plan.id, tasks_json)

        updated = plan_manager.get_plan(plan.id)
        assert len(updated.tasks) == 2
        assert updated.tasks[1].dependencies == ["task-1"]

    def test_add_tasks_invalid_json(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = add_plan_tasks(mock_context, plan.id, "not valid json")

        assert "Error" in result
        assert "Invalid JSON" in result


class TestReadPlan:
    """Tests for read_plan tool."""

    def test_read_existing_plan(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.context = "Test context"
        plan.approach = "Test approach"
        plan_manager.update_plan(plan)

        result = read_plan(mock_context, plan.id)

        assert "# Plan: Test Plan" in result
        assert "Test context" in result
        assert "Test approach" in result

    def test_read_nonexistent_plan(self, mock_context):
        result = read_plan(mock_context, "nonexistent")

        assert "Error" in result
        assert "not found" in result


class TestListPlans:
    """Tests for list_plans tool."""

    def test_list_active_plans(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan_manager.create_plan("Plan 1", "session1", root_dir=str(temp_persona_dir))
        plan_manager.create_plan("Plan 2", "session2", root_dir=str(temp_persona_dir))

        result = list_plans(mock_context, include_completed=False)

        assert "Active Plans" in result
        assert "Plan 1" in result
        assert "Plan 2" in result

    def test_list_with_completed(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan_manager.create_plan(
            "Active Plan", "session1", root_dir=str(temp_persona_dir)
        )
        plan2 = plan_manager.create_plan(
            "Done Plan", "session2", root_dir=str(temp_persona_dir)
        )

        # Complete one plan
        plan_manager.submit_for_review(plan2.id)
        plan_manager.approve_plan(plan2.id)
        plan_manager.complete_plan(plan2.id)

        result = list_plans(mock_context, include_completed=True)

        assert "Active Plans" in result
        assert "Completed Plans" in result
        assert "Active Plan" in result
        assert "Done Plan" in result

    def test_list_empty(self, mock_context, temp_persona_dir):
        result = list_plans(mock_context)

        assert "No active plans" in result


class TestExitPlanMode:
    """Tests for exit_plan_mode tool."""

    def test_exit_save_draft(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = exit_plan_mode(mock_context, plan.id, action="save")

        assert "Plan Mode Exited" in result
        assert "saved as draft" in result

        # Plan should still be in DRAFT status
        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.DRAFT

    def test_exit_submit_for_review(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = exit_plan_mode(mock_context, plan.id, action="submit")

        assert "Plan Submitted for Review" in result

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.IN_REVIEW

    def test_exit_execute_approved(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)

        result = exit_plan_mode(mock_context, plan.id, action="execute")

        assert "Plan Execution Started" in result

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.IN_PROGRESS

    def test_exit_execute_not_approved(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = exit_plan_mode(mock_context, plan.id, action="execute")

        assert "Error" in result
        assert "approved" in result.lower()

    def test_exit_abandon(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = exit_plan_mode(mock_context, plan.id, action="abandon")

        assert "Plan Abandoned" in result

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.ABANDONED

    def test_exit_invalid_action(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = exit_plan_mode(mock_context, plan.id, action="invalid")

        assert "Error" in result
        assert "Invalid action" in result


class TestCompletePlanTask:
    """Tests for complete_plan_task tool."""

    @pytest.mark.asyncio
    async def test_complete_task(self, mock_context, temp_persona_dir):
        """Test completing a task on an approved plan."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Test task")
        plan_manager.update_plan(plan)

        # Approve the plan first (required for implementation tasks)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        result = await complete_plan_task(mock_context, plan.id, task.id)

        assert "completed" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].completed is True

    @pytest.mark.asyncio
    async def test_complete_task_with_notes(self, mock_context, temp_persona_dir):
        """Test completing a task with notes on an approved plan."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Test task")
        plan_manager.update_plan(plan)

        # Approve the plan first
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        result = await complete_plan_task(
            mock_context, plan.id, task.id, notes="Finished with tests"
        )

        assert "completed" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        # Check progress log has the notes
        assert any("Finished with tests" in p.message for p in updated.progress_log)

    @pytest.mark.asyncio
    async def test_complete_implementation_task_requires_approval_interactive(
        self, mock_context, temp_persona_dir
    ):
        """Test that implementation tasks require approval in interactive mode."""
        from silica.developer.plans import APPROVAL_POLICY_INTERACTIVE

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.approval_policy = APPROVAL_POLICY_INTERACTIVE
        task = plan.add_task("Implementation task")
        plan_manager.update_plan(plan)

        result = await complete_plan_task(mock_context, plan.id, task.id)

        # Should return error asking for approval
        assert "not approved" in result.lower()
        assert "request_plan_approval" in result

    @pytest.mark.asyncio
    async def test_complete_implementation_task_auto_promotes_autonomous(
        self, mock_context, temp_persona_dir
    ):
        """Test that implementation tasks auto-promote plan in autonomous mode."""
        from silica.developer.plans import APPROVAL_POLICY_AUTONOMOUS

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.approval_policy = APPROVAL_POLICY_AUTONOMOUS
        task = plan.add_task("Implementation task")
        plan_manager.update_plan(plan)

        result = await complete_plan_task(mock_context, plan.id, task.id)

        # Should auto-promote and complete
        assert "completed" in result.lower()
        assert "auto-promoted" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.IN_PROGRESS
        assert updated.tasks[0].completed is True

    @pytest.mark.asyncio
    async def test_complete_exploration_task_no_approval_needed(
        self, mock_context, temp_persona_dir
    ):
        """Test that exploration tasks can be completed without approval."""
        from silica.developer.plans import CATEGORY_EXPLORATION

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Research task", category=CATEGORY_EXPLORATION)
        plan_manager.update_plan(plan)

        result = await complete_plan_task(mock_context, plan.id, task.id)

        # Should complete without requiring approval
        assert "completed" in result.lower()
        assert "exploration" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].completed is True
        # Plan status should remain DRAFT
        assert updated.status == PlanStatus.DRAFT

    @pytest.mark.asyncio
    async def test_complete_nonexistent_task(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = await complete_plan_task(mock_context, plan.id, "nonexistent")

        assert "Error" in result
        assert "not found" in result


class TestVerifyPlanTask:
    """Tests for verify_plan_task tool."""

    @pytest.mark.asyncio
    async def test_verify_completed_task(self, mock_context, temp_persona_dir):
        """Test verifying a completed task on an approved plan."""
        from silica.developer.tools.planning import verify_plan_task

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Test task")
        plan.complete_task(task.id)
        plan_manager.update_plan(plan)

        # Approve the plan first (required for implementation tasks)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        result = await verify_plan_task(
            mock_context, plan.id, task.id, "All tests pass: 10/10"
        )

        assert "verified" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].verified is True
        assert "10/10" in updated.tasks[0].verification_notes

    @pytest.mark.asyncio
    async def test_verify_incomplete_task_fails(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import verify_plan_task

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Test task")
        plan_manager.update_plan(plan)

        result = await verify_plan_task(mock_context, plan.id, task.id, "Tests pass")

        assert "Error" in result
        assert "completed" in result.lower()

    @pytest.mark.asyncio
    async def test_verify_requires_test_results(self, mock_context, temp_persona_dir):
        """Test that verification requires test results."""
        from silica.developer.tools.planning import verify_plan_task

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Test task")
        plan.complete_task(task.id)
        plan_manager.update_plan(plan)

        # Approve the plan first
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        result = await verify_plan_task(mock_context, plan.id, task.id, "")

        assert "Error" in result
        assert "required" in result.lower()

    @pytest.mark.asyncio
    async def test_verify_nonexistent_task(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import verify_plan_task

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = await verify_plan_task(
            mock_context, plan.id, "nonexistent", "Tests pass"
        )

        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_verify_exploration_task_no_approval_needed(
        self, mock_context, temp_persona_dir
    ):
        """Test that exploration tasks can be verified without approval."""
        from silica.developer.tools.planning import verify_plan_task
        from silica.developer.plans import CATEGORY_EXPLORATION

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Research task", category=CATEGORY_EXPLORATION)
        plan.complete_task(task.id)
        plan_manager.update_plan(plan)

        result = await verify_plan_task(
            mock_context, plan.id, task.id, "Research complete"
        )

        # Should verify without requiring approval
        assert "verified" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].verified is True
        # Plan status should remain DRAFT
        assert updated.status == PlanStatus.DRAFT


class TestCompletePlan:
    """Tests for complete_plan tool."""

    def test_complete_plan_all_tasks_done(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Test task")
        plan.complete_task(task.id)
        plan.verify_task(task.id, "Tests pass")  # Must verify before completing plan
        plan_manager.update_plan(plan)

        # Approve the plan first
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)

        result = complete_plan(mock_context, plan.id, notes="All done!")

        assert "Plan Completed" in result

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.COMPLETED
        assert updated.completion_notes == "All done!"

    def test_complete_plan_tasks_incomplete(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Incomplete task")
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)

        result = complete_plan(mock_context, plan.id)

        assert "Cannot complete plan" in result
        assert "incomplete" in result.lower()

    def test_complete_plan_tasks_unverified(self, mock_context, temp_persona_dir):
        """Tasks that are completed but not verified should block plan completion."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Unverified task")
        plan.complete_task(task.id)  # Completed but not verified
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)

        result = complete_plan(mock_context, plan.id)

        assert "Cannot complete plan" in result
        assert "not verified" in result.lower()

    def test_complete_plan_wrong_status(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = complete_plan(mock_context, plan.id)

        assert "Error" in result


class TestPlanManagerFromContext:
    """Tests for _get_plan_manager helper."""

    def test_with_history_base_dir(self, temp_persona_dir):
        context = MagicMock()
        context.history_base_dir = temp_persona_dir

        manager = _get_plan_manager(context)

        assert manager.base_dir == temp_persona_dir

    def test_without_history_base_dir(self):
        context = MagicMock()
        context.history_base_dir = None

        manager = _get_plan_manager(context)

        expected = Path.home() / ".silica" / "personas" / "default"
        assert manager.base_dir == expected


class TestGetActivePlanStatus:
    """Tests for get_active_plan_status function."""

    def test_no_active_plans(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import get_active_plan_status

        status = get_active_plan_status(mock_context)
        assert status is None

    def test_draft_plan_shows_planning(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import get_active_plan_status

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task 1")
        plan_manager.update_plan(plan)

        status = get_active_plan_status(mock_context)

        assert status is not None
        assert status["id"] == plan.id
        assert status["title"] == "Test Plan"
        assert status["status"] == "planning"

    def test_in_review_shows_planning(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import get_active_plan_status

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)

        status = get_active_plan_status(mock_context)

        assert status is not None
        assert status["status"] == "planning"

    def test_in_progress_shows_executing(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import get_active_plan_status

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task 1")
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        status = get_active_plan_status(mock_context)

        assert status is not None
        assert status["status"] == "executing"
        assert status["total_tasks"] == 1
        assert status["incomplete_tasks"] == 1

    def test_task_progress_tracking(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import get_active_plan_status

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task1 = plan.add_task("Task 1")
        plan.add_task("Task 2")
        plan.complete_task(task1.id)
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        status = get_active_plan_status(mock_context)

        assert status["total_tasks"] == 2
        assert status["incomplete_tasks"] == 1  # task2 still incomplete


class TestGetActivePlanReminder:
    """Tests for get_active_plan_reminder function."""

    def test_no_active_plans(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import get_active_plan_reminder

        reminder = get_active_plan_reminder(mock_context)
        assert reminder is None

    def test_plan_not_in_progress(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import get_active_plan_reminder

        # Create a draft plan (not in progress)
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task 1")
        plan_manager.update_plan(plan)

        reminder = get_active_plan_reminder(mock_context)
        assert reminder is None

    def test_plan_in_progress_with_tasks(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import get_active_plan_reminder

        # Create and progress a plan
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task(
            "Implement feature", files=["main.py"], details="Add the new code"
        )
        plan_manager.update_plan(plan)

        # Progress to in-progress status
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        reminder = get_active_plan_reminder(mock_context)

        assert reminder is not None
        assert "Active Plan Reminder" in reminder
        assert "Test Plan" in reminder
        assert task.id in reminder
        assert "Implement feature" in reminder
        assert "main.py" in reminder
        assert "complete_plan_task" in reminder

    def test_plan_in_progress_all_tasks_complete_but_unverified(
        self, mock_context, temp_persona_dir
    ):
        """Reminder should show when tasks are complete but not verified."""
        from silica.developer.tools.planning import get_active_plan_reminder

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Task 1")
        plan.complete_task(task.id)  # Complete but not verified
        plan_manager.update_plan(plan)

        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        reminder = get_active_plan_reminder(mock_context)
        assert reminder is not None  # Should remind about verification
        assert "verification" in reminder.lower()

    def test_plan_in_progress_all_tasks_verified(self, mock_context, temp_persona_dir):
        """No reminder when all tasks are verified."""
        from silica.developer.tools.planning import get_active_plan_reminder

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Task 1")
        plan.complete_task(task.id)
        plan.verify_task(task.id, "Tests pass")  # Both complete and verified
        plan_manager.update_plan(plan)

        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        reminder = get_active_plan_reminder(mock_context)
        assert reminder is None  # All verified, no reminder needed


class TestGetTaskCompletionHint:
    """Tests for get_task_completion_hint function."""

    def test_no_modified_files(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import get_task_completion_hint

        hint = get_task_completion_hint(mock_context, [])
        assert hint is None

    def test_no_active_plans(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import get_task_completion_hint

        hint = get_task_completion_hint(mock_context, ["some_file.py"])
        assert hint is None

    def test_modified_file_matches_task(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import get_task_completion_hint

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Update main", files=["main.py"])
        plan_manager.update_plan(plan)

        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        hint = get_task_completion_hint(mock_context, ["main.py"])

        assert hint is not None
        assert "Task Hint" in hint
        assert task.id in hint
        assert "complete_plan_task" in hint

    def test_modified_file_no_match(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import get_task_completion_hint

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Update main", files=["main.py"])
        plan_manager.update_plan(plan)

        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        hint = get_task_completion_hint(mock_context, ["other_file.py"])
        assert hint is None

    def test_task_without_files(self, mock_context, temp_persona_dir):
        from silica.developer.tools.planning import get_task_completion_hint

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task without files")  # No files specified
        plan_manager.update_plan(plan)

        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        hint = get_task_completion_hint(mock_context, ["any_file.py"])
        assert hint is None


class TestReopenPlan:
    """Tests for reopen_plan tool."""

    def test_reopen_completed_plan(self, mock_context, temp_persona_dir):
        """Test reopening a completed plan via the tool."""
        # Create and complete a plan
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task 1")
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)
        plan_manager.complete_plan(plan.id)

        # Set initial active_plan_id to None
        mock_context.active_plan_id = None

        # Reopen via tool
        result = reopen_plan(mock_context, plan.id, "Need to add more features")

        assert "Plan Reopened" in result
        assert plan.id in result
        assert "Need to add more features" in result

        # Check context was updated
        assert mock_context.active_plan_id == plan.id

        # Verify plan state
        reopened = plan_manager.get_plan(plan.id)
        assert reopened.status == PlanStatus.IN_PROGRESS

    def test_reopen_abandoned_plan(self, mock_context, temp_persona_dir):
        """Test reopening an abandoned plan."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Abandoned Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan_manager.abandon_plan(plan.id)

        mock_context.active_plan_id = None
        result = reopen_plan(mock_context, plan.id)

        assert "Plan Reopened" in result
        assert mock_context.active_plan_id == plan.id

    def test_reopen_nonexistent_plan(self, mock_context, temp_persona_dir):
        """Test error when reopening nonexistent plan."""
        result = reopen_plan(mock_context, "nonexistent")
        assert "Error" in result
        assert "not found" in result

    def test_reopen_active_plan_fails(self, mock_context, temp_persona_dir):
        """Test error when trying to reopen an active plan."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Active Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = reopen_plan(mock_context, plan.id)
        assert "Error" in result
        assert "COMPLETED or ABANDONED" in result

    def test_reopen_shows_task_summary(self, mock_context, temp_persona_dir):
        """Test that reopening shows task completion summary."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Task Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task1 = plan.add_task("Completed task")
        plan.add_task("Incomplete task")
        plan.complete_task(task1.id)
        plan.verify_task(task1.id, "Tests passed")
        plan_manager.update_plan(plan)

        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.complete_plan(plan.id)

        mock_context.active_plan_id = None
        result = reopen_plan(mock_context, plan.id)

        assert "Task Status" in result
        assert "1 verified" in result
        assert "1 incomplete" in result


class TestApprovePushFlagParsing:
    """Tests for the --push flag parsing in /plan approve.

    These tests verify the flag parsing logic. Full integration tests
    require a running antennae server.
    """

    def test_parse_push_flag_with_workspace(self):
        """Test parsing --push with workspace name."""
        # Simulate the parsing logic from toolbox._plan
        args_list = ["approve", "plan123 --push my-workspace"]

        push_workspace = None
        plan_id = None
        shelve = False

        if len(args_list) >= 2:
            args_parts = args_list[1].split()
            i = 0
            while i < len(args_parts):
                arg = args_parts[i]
                if arg == "--shelve":
                    shelve = True
                elif arg == "--push":
                    if i + 1 < len(args_parts) and not args_parts[i + 1].startswith(
                        "-"
                    ):
                        push_workspace = args_parts[i + 1]
                        i += 1
                    else:
                        push_workspace = ""
                elif arg.startswith("--push="):
                    push_workspace = arg.split("=", 1)[1]
                elif not plan_id and not arg.startswith("-"):
                    plan_id = arg
                i += 1

        assert plan_id == "plan123"
        assert push_workspace == "my-workspace"
        assert shelve is False

    def test_parse_push_flag_without_workspace(self):
        """Test parsing --push without workspace name (use default)."""
        args_list = ["approve", "plan123 --push"]

        push_workspace = None
        plan_id = None

        if len(args_list) >= 2:
            args_parts = args_list[1].split()
            i = 0
            while i < len(args_parts):
                arg = args_parts[i]
                if arg == "--push":
                    if i + 1 < len(args_parts) and not args_parts[i + 1].startswith(
                        "-"
                    ):
                        push_workspace = args_parts[i + 1]
                        i += 1
                    else:
                        push_workspace = ""
                elif arg.startswith("--push="):
                    push_workspace = arg.split("=", 1)[1]
                elif not plan_id and not arg.startswith("-"):
                    plan_id = arg
                i += 1

        assert plan_id == "plan123"
        assert push_workspace == ""  # Empty string means use default slug

    def test_parse_push_equals_syntax(self):
        """Test parsing --push=workspace syntax."""
        args_list = ["approve", "plan123 --push=remote-ws"]

        push_workspace = None
        plan_id = None

        if len(args_list) >= 2:
            args_parts = args_list[1].split()
            i = 0
            while i < len(args_parts):
                arg = args_parts[i]
                if arg == "--push":
                    if i + 1 < len(args_parts) and not args_parts[i + 1].startswith(
                        "-"
                    ):
                        push_workspace = args_parts[i + 1]
                        i += 1
                    else:
                        push_workspace = ""
                elif arg.startswith("--push="):
                    push_workspace = arg.split("=", 1)[1]
                elif not plan_id and not arg.startswith("-"):
                    plan_id = arg
                i += 1

        assert plan_id == "plan123"
        assert push_workspace == "remote-ws"

    def test_push_overrides_shelve(self):
        """Test that --push overrides --shelve."""
        # The actual implementation sets shelve=False when push_workspace is not None
        # This is handled in the toolbox code, we just verify the expected behavior
        args_list = ["approve", "plan123 --shelve --push my-ws"]

        push_workspace = None
        plan_id = None
        shelve = False

        if len(args_list) >= 2:
            args_parts = args_list[1].split()
            i = 0
            while i < len(args_parts):
                arg = args_parts[i]
                if arg == "--shelve":
                    shelve = True
                elif arg == "--push":
                    if i + 1 < len(args_parts) and not args_parts[i + 1].startswith(
                        "-"
                    ):
                        push_workspace = args_parts[i + 1]
                        i += 1
                    else:
                        push_workspace = ""
                elif arg.startswith("--push="):
                    push_workspace = arg.split("=", 1)[1]
                elif not plan_id and not arg.startswith("-"):
                    plan_id = arg
                i += 1

        # In actual code, push_workspace being not None causes shelve to be set to False
        if push_workspace is not None:
            shelve = False

        assert plan_id == "plan123"
        assert push_workspace == "my-ws"
        assert shelve is False


class TestPushWorkflowStateTransitions:
    """Tests for plan state transitions during push workflow.

    These tests verify the state machine behavior when pushing plans
    to remote workspaces. Full integration tests with --local flag
    require a running antennae server.
    """

    def test_push_transitions_to_in_progress(self, temp_persona_dir):
        """Test that successful push transitions plan to IN_PROGRESS."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Push Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)

        assert plan_manager.get_plan(plan.id).status == PlanStatus.APPROVED

        # Simulate what happens after successful push
        plan_manager.start_execution(plan.id)

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.IN_PROGRESS

    def test_push_sets_remote_workspace_info(self, temp_persona_dir):
        """Test that push sets remote workspace and branch info."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Remote Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)

        # Simulate push updating plan with remote info
        plan = plan_manager.get_plan(plan.id)
        plan.remote_workspace = "plan-remote-plan"
        plan.remote_branch = "plan/remote-plan"
        plan.shelved = False
        plan.add_progress("Pushed to remote workspace: plan-remote-plan")
        plan_manager.update_plan(plan)
        plan_manager.start_execution(plan.id)

        updated = plan_manager.get_plan(plan.id)
        assert updated.remote_workspace == "plan-remote-plan"
        assert updated.remote_branch == "plan/remote-plan"
        assert updated.status == PlanStatus.IN_PROGRESS
        assert updated.shelved is False

    def test_plan_slug_generation(self, temp_persona_dir):
        """Test that plan slugs are generated correctly for workspace names."""
        from silica.developer.plans import slugify

        # Test various plan titles
        assert slugify("Add User Avatars") == "add-user-avatars"
        assert slugify("Fix bug #123") == "fix-bug-123"
        assert slugify("Refactor auth/middleware") == "refactor-auth-middleware"
        assert slugify("Simple") == "simple"
        assert slugify("A" * 100) == "a" * 50  # Truncated to max_length

        # Test with actual plan
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Add New Feature X", "session123", root_dir=str(temp_persona_dir)
        )
        assert plan.get_slug() == "add-new-feature-x"

    def test_approve_then_push_workflow(self, temp_persona_dir):
        """Test the full approve-then-push workflow state transitions."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Full Workflow Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task 1", files=["main.py"])
        plan_manager.update_plan(plan)

        # Step 1: Submit for review
        plan_manager.submit_for_review(plan.id)
        assert plan_manager.get_plan(plan.id).status == PlanStatus.IN_REVIEW

        # Step 2: Approve (not shelved, ready for push)
        plan_manager.approve_plan(plan.id, shelve=False)
        assert plan_manager.get_plan(plan.id).status == PlanStatus.APPROVED

        # Step 3: Simulate push - update remote info and start execution
        plan = plan_manager.get_plan(plan.id)
        plan.remote_workspace = f"plan-{plan.get_slug()}"
        plan.remote_branch = f"plan/{plan.get_slug()}"
        plan.add_progress(f"Pushed to remote workspace: {plan.remote_workspace}")
        plan_manager.update_plan(plan)
        plan_manager.start_execution(plan.id)

        # Verify final state
        final = plan_manager.get_plan(plan.id)
        assert final.status == PlanStatus.IN_PROGRESS
        assert final.remote_workspace == "plan-full-workflow-plan"
        assert final.remote_branch == "plan/full-workflow-plan"
        assert any("Pushed to remote" in e.message for e in final.progress_log)


class TestGetActivePlanStatusSlug:
    """Tests for get_active_plan_status returning slug for token summary."""

    def test_get_active_plan_status_includes_slug(self, mock_context, temp_persona_dir):
        """Test that get_active_plan_status returns slug field."""
        from silica.developer.tools.planning import get_active_plan_status

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Add User Avatars", "session123", root_dir=str(temp_persona_dir)
        )
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        status = get_active_plan_status(mock_context)

        assert status is not None
        assert "slug" in status
        assert status["slug"] == "add-user-avatars"

    def test_get_active_plan_status_slug_special_chars(
        self, mock_context, temp_persona_dir
    ):
        """Test slug generation handles special characters."""
        from silica.developer.tools.planning import get_active_plan_status

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Fix Bug #123: Auth/OAuth Issue",
            "session123",
            root_dir=str(temp_persona_dir),
        )
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        status = get_active_plan_status(mock_context)

        assert status is not None
        assert status["slug"] == "fix-bug-123-auth-oauth-issue"

    def test_plan_status_for_token_summary_executing(
        self, mock_context, temp_persona_dir
    ):
        """Test plan status fields needed for token summary display."""
        from silica.developer.tools.planning import get_active_plan_status

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Feature", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task 1")
        plan.add_task("Task 2")
        plan.add_task("Task 3")
        plan.tasks[0].completed = True
        plan.tasks[0].verified = True
        plan.tasks[1].completed = True
        plan_manager.update_plan(plan)

        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        status = get_active_plan_status(mock_context)

        assert status is not None
        assert status["status"] == "executing"
        assert status["slug"] == "test-feature"
        assert status["total_tasks"] == 3
        assert status["verified_tasks"] == 1
        assert status["incomplete_tasks"] == 1  # Task 3 is incomplete

    def test_plan_status_not_shown_when_planning(self, mock_context, temp_persona_dir):
        """Test that plan status is 'planning' for draft/in-review plans."""
        from silica.developer.tools.planning import get_active_plan_status

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Draft Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task 1")
        plan_manager.update_plan(plan)

        # Draft plan
        status = get_active_plan_status(mock_context)
        assert status is not None
        assert status["status"] == "planning"
        assert "slug" in status  # Slug should still be available

        # In review plan
        plan_manager.submit_for_review(plan.id)
        status = get_active_plan_status(mock_context)
        assert status["status"] == "planning"
