"""Tests for plan task management tools (cancel, remove, update, bulk operations)."""

import json
import pytest
from unittest.mock import MagicMock

from silica.developer.plans import PlanManager, PlanStatus
from silica.developer.tools.planning import (
    cancel_plan_task,
    uncancel_plan_task,
    remove_plan_task,
    update_plan_task,
    bulk_cancel_tasks,
    replace_plan_tasks,
    list_cancelled_tasks,
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
    context.sandbox = MagicMock()
    context.sandbox.root_directory = temp_persona_dir
    context.active_plan_id = None
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


class TestCancelPlanTask:
    """Tests for cancel_plan_task tool."""

    def test_cancel_task_basic(self, mock_context, temp_persona_dir):
        """Test basic task cancellation."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Task to cancel")
        plan_manager.update_plan(plan)

        result = cancel_plan_task(mock_context, plan.id, task.id)

        assert "cancelled" in result.lower()
        assert task.id in result

        # Verify task state
        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].cancelled is True

    def test_cancel_task_with_reason(self, mock_context, temp_persona_dir):
        """Test task cancellation with reason."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Task to cancel")
        plan_manager.update_plan(plan)

        result = cancel_plan_task(
            mock_context, plan.id, task.id, reason="Requirements changed"
        )

        assert "Requirements changed" in result

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].cancelled_reason == "Requirements changed"

    def test_cancel_already_cancelled_task(self, mock_context, temp_persona_dir):
        """Test cancelling already cancelled task."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Task")
        plan.cancel_task(task.id)
        plan_manager.update_plan(plan)

        result = cancel_plan_task(mock_context, plan.id, task.id)

        assert "already cancelled" in result.lower()

    def test_cancel_nonexistent_task(self, mock_context, temp_persona_dir):
        """Test cancelling nonexistent task."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = cancel_plan_task(mock_context, plan.id, "nonexistent")

        assert "Error" in result
        assert "not found" in result

    def test_cancelled_task_excluded_from_incomplete(
        self, mock_context, temp_persona_dir
    ):
        """Test that cancelled tasks are excluded from incomplete list."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task1 = plan.add_task("Task 1")
        task2 = plan.add_task("Task 2")
        plan_manager.update_plan(plan)

        # Before cancellation
        assert len(plan.get_incomplete_tasks()) == 2

        cancel_plan_task(mock_context, plan.id, task1.id)

        # After cancellation
        updated = plan_manager.get_plan(plan.id)
        incomplete = updated.get_incomplete_tasks()
        assert len(incomplete) == 1
        assert incomplete[0].id == task2.id


class TestUncancelPlanTask:
    """Tests for uncancel_plan_task tool."""

    def test_uncancel_task(self, mock_context, temp_persona_dir):
        """Test restoring a cancelled task."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Task")
        plan.cancel_task(task.id, "Test reason")
        plan_manager.update_plan(plan)

        result = uncancel_plan_task(mock_context, plan.id, task.id)

        assert "restored" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].cancelled is False
        assert updated.tasks[0].cancelled_reason == ""

    def test_uncancel_non_cancelled_task(self, mock_context, temp_persona_dir):
        """Test uncancelling a non-cancelled task."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Task")
        plan_manager.update_plan(plan)

        result = uncancel_plan_task(mock_context, plan.id, task.id)

        assert "not cancelled" in result.lower()


class TestRemovePlanTask:
    """Tests for remove_plan_task tool."""

    def test_remove_task(self, mock_context, temp_persona_dir):
        """Test removing a task."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Task to remove")
        plan_manager.update_plan(plan)

        result = remove_plan_task(mock_context, plan.id, task.id)

        assert "removed" in result.lower()
        assert task.id in result

        updated = plan_manager.get_plan(plan.id)
        assert len(updated.tasks) == 0

    def test_remove_task_cleans_dependencies(self, mock_context, temp_persona_dir):
        """Test that removing a task cleans up dependencies."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task1 = plan.add_task("Task 1")
        task2 = plan.add_task("Task 2", dependencies=[task1.id])
        plan_manager.update_plan(plan)

        remove_plan_task(mock_context, plan.id, task1.id)

        updated = plan_manager.get_plan(plan.id)
        assert len(updated.tasks) == 1
        assert updated.tasks[0].id == task2.id
        assert task1.id not in updated.tasks[0].dependencies

    def test_remove_task_removes_subtasks(self, mock_context, temp_persona_dir):
        """Test that removing a parent task removes its subtasks."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        parent = plan.add_task("Parent task")
        child = plan.add_task("Child task")
        child.parent_task_id = parent.id
        plan_manager.update_plan(plan)

        result = remove_plan_task(mock_context, plan.id, parent.id)

        assert "subtask" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        assert len(updated.tasks) == 0

    def test_remove_nonexistent_task(self, mock_context, temp_persona_dir):
        """Test removing nonexistent task."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        result = remove_plan_task(mock_context, plan.id, "nonexistent")

        assert "Error" in result
        assert "not found" in result


class TestUpdatePlanTask:
    """Tests for update_plan_task tool."""

    def test_update_description(self, mock_context, temp_persona_dir):
        """Test updating task description."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Original description")
        plan_manager.update_plan(plan)

        result = update_plan_task(
            mock_context, plan.id, task.id, description="Updated description"
        )

        assert "updated" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].description == "Updated description"

    def test_update_multiple_fields(self, mock_context, temp_persona_dir):
        """Test updating multiple fields."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Task")
        plan_manager.update_plan(plan)

        result = update_plan_task(
            mock_context,
            plan.id,
            task.id,
            description="New desc",
            details="New details",
            files="file1.py, file2.py",
            tests="Unit tests required",
        )

        assert "updated" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        task = updated.tasks[0]
        assert task.description == "New desc"
        assert task.details == "New details"
        assert task.files == ["file1.py", "file2.py"]
        assert task.tests == "Unit tests required"

    def test_update_no_fields(self, mock_context, temp_persona_dir):
        """Test update with no fields provided."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Task")
        plan_manager.update_plan(plan)

        result = update_plan_task(mock_context, plan.id, task.id)

        assert "No updates provided" in result


class TestBulkCancelTasks:
    """Tests for bulk_cancel_tasks tool."""

    def test_bulk_cancel_multiple(self, mock_context, temp_persona_dir):
        """Test cancelling multiple tasks."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task1 = plan.add_task("Task 1")
        task2 = plan.add_task("Task 2")
        plan.add_task("Task 3")  # Keep task3 active
        plan_manager.update_plan(plan)

        result = bulk_cancel_tasks(
            mock_context, plan.id, f"{task1.id}, {task2.id}", reason="Obsolete"
        )

        assert "Bulk Cancel Summary" in result
        assert task1.id in result
        assert task2.id in result
        assert "Obsolete" in result

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].cancelled is True
        assert updated.tasks[1].cancelled is True
        assert updated.tasks[2].cancelled is False

    def test_bulk_cancel_mixed_results(self, mock_context, temp_persona_dir):
        """Test bulk cancel with some already cancelled and some not found."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task1 = plan.add_task("Task 1")
        task2 = plan.add_task("Task 2")
        plan.cancel_task(task2.id)  # Pre-cancel
        plan_manager.update_plan(plan)

        result = bulk_cancel_tasks(
            mock_context, plan.id, f"{task1.id}, {task2.id}, nonexistent"
        )

        assert "Cancelled" in result
        assert "Already cancelled" in result
        assert "Not found" in result


class TestReplacePlanTasks:
    """Tests for replace_plan_tasks tool."""

    def test_replace_tasks_archive_old(self, mock_context, temp_persona_dir):
        """Test replacing tasks with archiving old ones."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Old task 1")
        plan.add_task("Old task 2")
        plan_manager.update_plan(plan)

        new_tasks = json.dumps(
            [{"description": "New task 1"}, {"description": "New task 2"}]
        )

        result = replace_plan_tasks(
            mock_context,
            plan.id,
            new_tasks,
            reason="Complete pivot",
            archive_old=True,
        )

        assert "Plan Tasks Replaced" in result
        assert "Complete pivot" in result
        assert "2 cancelled" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        # 2 old (cancelled) + 2 new
        assert len(updated.tasks) == 4
        cancelled = [t for t in updated.tasks if t.cancelled]
        active = [t for t in updated.tasks if not t.cancelled]
        assert len(cancelled) == 2
        assert len(active) == 2

    def test_replace_tasks_remove_old(self, mock_context, temp_persona_dir):
        """Test replacing tasks with removing old ones."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Old task 1")
        plan.add_task("Old task 2")
        plan_manager.update_plan(plan)

        new_tasks = json.dumps([{"description": "New task 1"}])

        result = replace_plan_tasks(mock_context, plan.id, new_tasks, archive_old=False)

        assert "removed" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        assert len(updated.tasks) == 1
        assert updated.tasks[0].description == "New task 1"

    def test_replace_with_dependencies(self, mock_context, temp_persona_dir):
        """Test replacing with new tasks that have dependencies."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Old task")
        plan_manager.update_plan(plan)

        new_tasks = json.dumps(
            [
                {"description": "Setup", "files": ["setup.py"]},
                {"description": "Implementation", "dependencies": []},
            ]
        )

        result = replace_plan_tasks(mock_context, plan.id, new_tasks, archive_old=False)

        assert "Setup" in result
        assert "Implementation" in result


class TestListCancelledTasks:
    """Tests for list_cancelled_tasks tool."""

    def test_list_cancelled_tasks(self, mock_context, temp_persona_dir):
        """Test listing cancelled tasks."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task1 = plan.add_task("Task 1")
        plan.add_task("Task 2")
        plan.cancel_task(task1.id, "No longer needed")
        plan_manager.update_plan(plan)

        result = list_cancelled_tasks(mock_context, plan.id)

        assert "Cancelled Tasks" in result
        assert task1.id in result
        assert "No longer needed" in result
        assert "uncancel_plan_task" in result

    def test_list_no_cancelled_tasks(self, mock_context, temp_persona_dir):
        """Test listing when no tasks are cancelled."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task 1")
        plan_manager.update_plan(plan)

        result = list_cancelled_tasks(mock_context, plan.id)

        assert "No cancelled tasks" in result


class TestCancelledTasksAndDependencies:
    """Tests for cancelled tasks interaction with dependencies."""

    def test_cancelled_dep_does_not_block(self, mock_context, temp_persona_dir):
        """Test that cancelled dependencies don't block tasks."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task1 = plan.add_task("Task 1")
        task2 = plan.add_task("Task 2", dependencies=[task1.id])
        plan_manager.update_plan(plan)

        # Task 2 should be blocked
        assert not plan.is_task_ready(task2.id)

        # Cancel task 1
        cancel_plan_task(mock_context, plan.id, task1.id)

        # Task 2 should now be ready
        updated = plan_manager.get_plan(plan.id)
        assert updated.is_task_ready(task2.id)

    def test_cancelled_task_not_in_ready_tasks(self, mock_context, temp_persona_dir):
        """Test that cancelled tasks don't appear in ready tasks."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task1 = plan.add_task("Task 1")
        task2 = plan.add_task("Task 2")
        plan_manager.update_plan(plan)

        # Both should be ready initially
        assert len(plan.get_ready_tasks()) == 2

        # Cancel task 1
        cancel_plan_task(mock_context, plan.id, task1.id)

        updated = plan_manager.get_plan(plan.id)
        ready = updated.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == task2.id


class TestCancelledTasksInMarkdown:
    """Tests for cancelled tasks rendering in markdown."""

    def test_cancelled_task_shows_strikethrough(self, temp_persona_dir):
        """Test that cancelled tasks show strikethrough in markdown."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")
        task = plan.add_task("Task to cancel")
        plan.cancel_task(task.id, "Test reason")
        plan_manager.update_plan(plan)

        markdown = plan.to_markdown()

        assert "~~Task to cancel~~" in markdown
        assert "🚫" in markdown
        assert "[CANCELLED: Test reason]" in markdown

    def test_cancelled_task_round_trip(self, temp_persona_dir):
        """Test that cancelled state survives serialization."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")
        task = plan.add_task("Task")
        plan.cancel_task(task.id, "Reason")
        plan_manager.update_plan(plan)

        # Reload from disk
        reloaded = plan_manager.get_plan(plan.id)
        assert reloaded.tasks[0].cancelled is True
        assert reloaded.tasks[0].cancelled_reason == "Reason"


class TestPlanCompletionWithCancelledTasks:
    """Tests for plan completion behavior with cancelled tasks."""

    def test_plan_completion_ignores_cancelled(self, mock_context, temp_persona_dir):
        """Test that cancelled tasks don't block plan completion."""
        from silica.developer.tools.planning import complete_plan

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )
        task1 = plan.add_task("Task 1")
        task2 = plan.add_task("Task 2")

        # Complete and verify task1
        plan.complete_task(task1.id)
        plan.verify_task(task1.id, "Tests pass")

        # Cancel task2 (incomplete)
        plan.cancel_task(task2.id, "Not needed")

        plan_manager.update_plan(plan)
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)

        # Should be able to complete plan
        result = complete_plan(mock_context, plan.id)

        assert "Plan Completed" in result

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.COMPLETED

    def test_all_tasks_verified_excludes_cancelled(self, temp_persona_dir):
        """Test that all_tasks_verified excludes cancelled tasks."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan("Test Plan", "session123")
        task1 = plan.add_task("Task 1")
        task2 = plan.add_task("Task 2")

        # Verify task1
        plan.complete_task(task1.id)
        plan.verify_task(task1.id, "Tests pass")

        # Cancel task2 without completing
        plan.cancel_task(task2.id)

        assert plan.all_tasks_verified() is True
