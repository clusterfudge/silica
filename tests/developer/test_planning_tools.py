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

    # Mock user_interface for ask_clarifications
    context.user_interface = MagicMock()
    context.user_interface.get_user_choice = AsyncMock(return_value="Option A")
    context.user_interface.get_user_input = AsyncMock(return_value="user input")

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
        plan = plan_manager.create_plan("Test Plan", "session123")

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
        plan = plan_manager.create_plan("Test Plan", "session123")

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
        plan = plan_manager.create_plan("Test Plan", "session123")

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
        plan = plan_manager.create_plan("Test Plan", "session123")

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
        plan = plan_manager.create_plan("Test Plan", "session123")

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
        plan = plan_manager.create_plan("Test Plan", "session123")

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
        plan = plan_manager.create_plan("Test Plan", "session123")

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
        plan = plan_manager.create_plan("Test Plan", "session123")

        result = add_plan_tasks(mock_context, plan.id, "not valid json")

        assert "Error" in result
        assert "Invalid JSON" in result


class TestReadPlan:
    """Tests for read_plan tool."""

    def test_read_existing_plan(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")
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
        plan_manager.create_plan("Plan 1", "session1")
        plan_manager.create_plan("Plan 2", "session2")

        result = list_plans(mock_context, include_completed=False)

        assert "Active Plans" in result
        assert "Plan 1" in result
        assert "Plan 2" in result

    def test_list_with_completed(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan_manager.create_plan("Active Plan", "session1")
        plan2 = plan_manager.create_plan("Done Plan", "session2")

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
        plan = plan_manager.create_plan("Test Plan", "session123")

        result = exit_plan_mode(mock_context, plan.id, action="save")

        assert "Plan Mode Exited" in result
        assert "saved as draft" in result

        # Plan should still be in DRAFT status
        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.DRAFT

    def test_exit_submit_for_review(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")

        result = exit_plan_mode(mock_context, plan.id, action="submit")

        assert "Plan Submitted for Review" in result

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.IN_REVIEW

    def test_exit_execute_approved(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)

        result = exit_plan_mode(mock_context, plan.id, action="execute")

        assert "Plan Execution Started" in result

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.IN_PROGRESS

    def test_exit_execute_not_approved(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")

        result = exit_plan_mode(mock_context, plan.id, action="execute")

        assert "Error" in result
        assert "approved" in result.lower()

    def test_exit_abandon(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")

        result = exit_plan_mode(mock_context, plan.id, action="abandon")

        assert "Plan Abandoned" in result

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.ABANDONED

    def test_exit_invalid_action(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")

        result = exit_plan_mode(mock_context, plan.id, action="invalid")

        assert "Error" in result
        assert "Invalid action" in result


class TestCompletePlanTask:
    """Tests for complete_plan_task tool."""

    def test_complete_task(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")
        task = plan.add_task("Test task")
        plan_manager.update_plan(plan)

        result = complete_plan_task(mock_context, plan.id, task.id)

        assert "completed" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].completed is True

    def test_complete_task_with_notes(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")
        task = plan.add_task("Test task")
        plan_manager.update_plan(plan)

        result = complete_plan_task(
            mock_context, plan.id, task.id, notes="Finished with tests"
        )

        assert "completed" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        # Check progress log has the notes
        assert any("Finished with tests" in p.message for p in updated.progress_log)

    def test_complete_nonexistent_task(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")

        result = complete_plan_task(mock_context, plan.id, "nonexistent")

        assert "Error" in result
        assert "not found" in result


class TestCompletePlan:
    """Tests for complete_plan tool."""

    def test_complete_plan_all_tasks_done(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")
        task = plan.add_task("Test task")
        plan.complete_task(task.id)
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
        plan = plan_manager.create_plan("Test Plan", "session123")
        plan.add_task("Incomplete task")
        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)

        result = complete_plan(mock_context, plan.id)

        assert "Warning" in result
        assert "incomplete" in result.lower()

    def test_complete_plan_wrong_status(self, mock_context, temp_persona_dir):
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")

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
