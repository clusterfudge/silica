"""Tests for plan approval flow improvements.

Tests for:
- Task categories (exploration vs implementation)
- Approval policies (interactive vs autonomous)
- Auto-promotion logic
- request_plan_approval tool (interactive approval)
- approve_plan tool (autonomous approval)
- approval_mode tracking
- Backwards compatibility
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from silica.developer.plans import (
    APPROVAL_MODE_AGENT,
    APPROVAL_MODE_SUBAGENT,
    APPROVAL_MODE_USER,
    APPROVAL_POLICY_AUTONOMOUS,
    APPROVAL_POLICY_INTERACTIVE,
    CATEGORY_EXPLORATION,
    CATEGORY_IMPLEMENTATION,
    Plan,
    PlanManager,
    PlanStatus,
    PlanTask,
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
    context.active_plan_id = None

    # Mock sandbox with root_directory for project scoping
    context.sandbox = MagicMock()
    context.sandbox.root_directory = temp_persona_dir

    # Mock user_interface for approval flows
    context.user_interface = MagicMock()
    context.user_interface.get_user_choice = AsyncMock(return_value="Option A")
    context.user_interface.get_input = AsyncMock(return_value="user input")
    context.user_interface.display = MagicMock()

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


class TestTaskCategories:
    """Tests for task category field."""

    def test_task_default_category_is_implementation(self):
        """New tasks default to implementation category."""
        task = PlanTask(id="test1", description="Test task")
        assert task.category == CATEGORY_IMPLEMENTATION
        assert task.is_implementation()
        assert not task.is_exploration()

    def test_task_exploration_category(self):
        """Tasks can be marked as exploration."""
        task = PlanTask(
            id="test1",
            description="Research task",
            category=CATEGORY_EXPLORATION,
        )
        assert task.category == CATEGORY_EXPLORATION
        assert task.is_exploration()
        assert not task.is_implementation()

    def test_task_category_serialization(self):
        """Task category is properly serialized and deserialized."""
        task = PlanTask(
            id="test1",
            description="Exploration task",
            category=CATEGORY_EXPLORATION,
        )
        data = task.to_dict()
        assert data["category"] == CATEGORY_EXPLORATION

        restored = PlanTask.from_dict(data)
        assert restored.category == CATEGORY_EXPLORATION
        assert restored.is_exploration()

    def test_task_category_default_not_in_serialization(self):
        """Default category (implementation) is not included in serialization."""
        task = PlanTask(id="test1", description="Normal task")
        data = task.to_dict()
        assert "category" not in data  # Default is not serialized

    def test_plan_get_exploration_tasks(self, temp_persona_dir):
        """Plan.get_exploration_tasks returns only exploration tasks."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )

        plan.add_task("Impl task 1")
        plan.add_task("Research", category=CATEGORY_EXPLORATION)
        plan.add_task("Impl task 2")
        plan_manager.update_plan(plan)

        expl_tasks = plan.get_exploration_tasks()
        impl_tasks = plan.get_implementation_tasks()

        assert len(expl_tasks) == 1
        assert expl_tasks[0].description == "Research"
        assert len(impl_tasks) == 2

    def test_plan_get_incomplete_by_category(self, temp_persona_dir):
        """Plan can filter incomplete tasks by category."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )

        t1 = plan.add_task("Impl task 1")
        plan.add_task("Research", category=CATEGORY_EXPLORATION)
        plan.add_task("Impl task 2")
        plan.complete_task(t1.id)
        plan_manager.update_plan(plan)

        incomplete_impl = plan.get_incomplete_implementation_tasks()
        incomplete_expl = plan.get_incomplete_exploration_tasks()

        assert len(incomplete_impl) == 1
        assert incomplete_impl[0].description == "Impl task 2"
        assert len(incomplete_expl) == 1
        assert incomplete_expl[0].description == "Research"


class TestApprovalPolicy:
    """Tests for approval policy field."""

    def test_plan_default_policy_is_interactive(self, temp_persona_dir):
        """New plans default to interactive approval policy."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )

        assert plan.approval_policy == APPROVAL_POLICY_INTERACTIVE
        assert plan.is_interactive()
        assert not plan.is_autonomous()

    def test_plan_autonomous_policy(self, temp_persona_dir):
        """Plans can use autonomous approval policy."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        plan.approval_policy = APPROVAL_POLICY_AUTONOMOUS
        plan_manager.update_plan(plan)

        loaded = plan_manager.get_plan(plan.id)
        assert loaded.approval_policy == APPROVAL_POLICY_AUTONOMOUS
        assert loaded.is_autonomous()

    def test_approval_mode_tracking(self, temp_persona_dir):
        """Approval mode is tracked when plan is approved."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )

        # Initially no approval mode
        assert plan.approval_mode is None

        # Simulate user approval
        plan.approval_mode = APPROVAL_MODE_USER
        plan_manager.update_plan(plan)

        loaded = plan_manager.get_plan(plan.id)
        assert loaded.approval_mode == APPROVAL_MODE_USER

    def test_is_approved_helper(self, temp_persona_dir):
        """Plan.is_approved() returns True for APPROVED or IN_PROGRESS."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )

        assert not plan.is_approved()

        plan.status = PlanStatus.IN_REVIEW
        assert not plan.is_approved()

        plan.status = PlanStatus.APPROVED
        assert plan.is_approved()

        plan.status = PlanStatus.IN_PROGRESS
        assert plan.is_approved()


class TestAutoPromotionLogic:
    """Tests for auto-promotion logic in complete_plan_task and verify_plan_task."""

    def test_exploration_task_completes_without_approval(
        self, mock_context, temp_persona_dir
    ):
        """Exploration tasks can be completed without plan approval."""
        from silica.developer.tools.planning import complete_plan_task

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Research", category=CATEGORY_EXPLORATION)
        plan_manager.update_plan(plan)

        result = complete_plan_task(mock_context, plan.id, task.id)

        assert "completed" in result.lower()
        assert "exploration" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].completed
        assert updated.status == PlanStatus.DRAFT  # Not promoted

    def test_implementation_task_blocked_interactive(
        self, mock_context, temp_persona_dir
    ):
        """Implementation tasks are blocked on unapproved interactive plans."""
        from silica.developer.tools.planning import complete_plan_task

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        plan.approval_policy = APPROVAL_POLICY_INTERACTIVE
        task = plan.add_task("Implement feature")
        plan_manager.update_plan(plan)

        result = complete_plan_task(mock_context, plan.id, task.id)

        assert "not approved" in result.lower()
        assert "request_plan_approval" in result

        updated = plan_manager.get_plan(plan.id)
        assert not updated.tasks[0].completed
        assert updated.status == PlanStatus.DRAFT

    def test_implementation_task_auto_promotes_autonomous(
        self, mock_context, temp_persona_dir
    ):
        """Implementation tasks auto-promote autonomous plans."""
        from silica.developer.tools.planning import complete_plan_task

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        plan.approval_policy = APPROVAL_POLICY_AUTONOMOUS
        task = plan.add_task("Implement feature")
        plan_manager.update_plan(plan)

        result = complete_plan_task(mock_context, plan.id, task.id)

        assert "completed" in result.lower()
        assert "auto-promoted" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].completed
        assert updated.status == PlanStatus.IN_PROGRESS
        assert updated.approval_mode == APPROVAL_MODE_AGENT

    def test_implementation_task_allowed_on_approved_plan(
        self, mock_context, temp_persona_dir
    ):
        """Implementation tasks work normally on approved plans."""
        from silica.developer.tools.planning import complete_plan_task

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Implement feature")
        plan_manager.update_plan(plan)

        # Approve the plan
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        result = complete_plan_task(mock_context, plan.id, task.id)

        assert "completed" in result.lower()
        assert "auto-promoted" not in result.lower()

    def test_verify_exploration_task_without_approval(
        self, mock_context, temp_persona_dir
    ):
        """Exploration tasks can be verified without plan approval."""
        from silica.developer.tools.planning import verify_plan_task

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        task = plan.add_task("Research", category=CATEGORY_EXPLORATION)
        plan.complete_task(task.id)
        plan_manager.update_plan(plan)

        result = verify_plan_task(mock_context, plan.id, task.id, "Research complete")

        assert "verified" in result.lower()

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].verified
        assert updated.status == PlanStatus.DRAFT


class TestApprovePlanTool:
    """Tests for approve_plan tool (autonomous approval)."""

    @pytest.mark.asyncio
    async def test_self_approval(self, mock_context, temp_persona_dir):
        """Agent can self-approve a plan."""
        from silica.developer.tools.planning import approve_plan

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task 1")
        plan_manager.update_plan(plan)

        result = await approve_plan(mock_context, plan.id, mode="self")

        assert "Self-Approved" in result
        assert plan.id in result

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.IN_PROGRESS
        assert updated.approval_mode == APPROVAL_MODE_AGENT

    @pytest.mark.asyncio
    async def test_self_approval_already_approved(self, mock_context, temp_persona_dir):
        """Self-approval of already approved plan gives helpful message."""
        from silica.developer.tools.planning import approve_plan

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)

        result = await approve_plan(mock_context, plan.id, mode="self")

        assert "already approved" in result.lower()

    @pytest.mark.asyncio
    async def test_subagent_approval_approves(self, mock_context, temp_persona_dir):
        """Sub-agent review can approve a plan."""
        from silica.developer.tools.planning import approve_plan
        from silica.developer.tools import subagent

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task 1")
        plan_manager.update_plan(plan)

        # Mock sub-agent to return approval
        original_agent = subagent.agent
        subagent.agent = AsyncMock(return_value="This plan looks good. APPROVE.")

        try:
            result = await approve_plan(mock_context, plan.id, mode="subagent")

            assert "Approved" in result
            assert "sub-agent review" in result.lower()

            updated = plan_manager.get_plan(plan.id)
            assert updated.status == PlanStatus.IN_PROGRESS
            assert updated.approval_mode == APPROVAL_MODE_SUBAGENT
        finally:
            subagent.agent = original_agent

    @pytest.mark.asyncio
    async def test_subagent_approval_requests_changes(
        self, mock_context, temp_persona_dir
    ):
        """Sub-agent review can request changes."""
        from silica.developer.tools.planning import approve_plan
        from silica.developer.tools import subagent

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Task 1")
        plan_manager.update_plan(plan)

        # Mock sub-agent to request changes
        original_agent = subagent.agent
        subagent.agent = AsyncMock(
            return_value="Missing error handling. REQUEST_CHANGES."
        )

        try:
            result = await approve_plan(mock_context, plan.id, mode="subagent")

            assert "Changes Requested" in result
            assert "Missing error handling" in result

            updated = plan_manager.get_plan(plan.id)
            assert updated.status != PlanStatus.IN_PROGRESS
        finally:
            subagent.agent = original_agent


class TestAddPlanTasksWithCategory:
    """Tests for add_plan_tasks tool with category support."""

    def test_add_exploration_task(self, mock_context, temp_persona_dir):
        """Tasks can be added with exploration category."""
        from silica.developer.tools.planning import add_plan_tasks

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )

        tasks_json = json.dumps(
            [
                {"description": "Research options", "category": "exploration"},
                {"description": "Implement solution"},
            ]
        )

        result = add_plan_tasks(mock_context, plan.id, tasks_json)

        assert "Added 2 tasks" in result
        assert "🔍" in result  # Exploration indicator

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].is_exploration()
        assert updated.tasks[1].is_implementation()

    def test_add_task_invalid_category_defaults_to_implementation(
        self, mock_context, temp_persona_dir
    ):
        """Invalid category defaults to implementation."""
        from silica.developer.tools.planning import add_plan_tasks

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )

        tasks_json = json.dumps(
            [
                {"description": "Task with bad category", "category": "invalid"},
            ]
        )

        add_plan_tasks(mock_context, plan.id, tasks_json)

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].is_implementation()


class TestBackwardsCompatibility:
    """Tests for backwards compatibility with existing plans."""

    def test_plan_without_approval_fields(self):
        """Plans without approval fields get defaults."""
        data = {
            "id": "test123",
            "title": "Old Plan",
            "status": "draft",
            "session_id": "session123",
            "tasks": [{"id": "t1", "description": "Task"}],
            # No approval_policy or approval_mode fields
        }

        plan = Plan.from_dict(data)

        assert plan.approval_policy == APPROVAL_POLICY_INTERACTIVE
        assert plan.approval_mode is None
        assert plan.tasks[0].category == CATEGORY_IMPLEMENTATION

    def test_task_without_category_field(self):
        """Tasks without category field default to implementation."""
        data = {
            "id": "t1",
            "description": "Old task",
            # No category field
        }

        task = PlanTask.from_dict(data)

        assert task.category == CATEGORY_IMPLEMENTATION
        assert task.is_implementation()


class TestMarkdownRendering:
    """Tests for markdown rendering of new fields."""

    def test_markdown_shows_approval_policy(self, temp_persona_dir):
        """Plan markdown includes approval policy."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        plan.approval_policy = APPROVAL_POLICY_AUTONOMOUS

        markdown = plan.to_markdown()

        assert "autonomous" in markdown.lower()

    def test_markdown_shows_approval_mode_when_set(self, temp_persona_dir):
        """Plan markdown includes approval mode when set."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        plan.approval_mode = APPROVAL_MODE_USER

        markdown = plan.to_markdown()

        assert "Approved By" in markdown
        assert "user" in markdown.lower()

    def test_markdown_shows_task_category_indicator(self, temp_persona_dir):
        """Plan markdown shows indicator for exploration tasks."""
        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test", "session", root_dir=str(temp_persona_dir)
        )
        plan.add_task("Normal task")
        plan.add_task("Research task", category=CATEGORY_EXPLORATION)

        markdown = plan.to_markdown()

        # Exploration tasks should have the indicator
        assert "🔍" in markdown
