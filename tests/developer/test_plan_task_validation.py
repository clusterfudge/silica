"""Tests for plan task validation feature."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from silica.developer.plans import (
    PlanTask,
    CATEGORY_EXPLORATION,
    CATEGORY_IMPLEMENTATION,
)


class TestPlanTaskValidationFields:
    """Tests for the new validation fields on PlanTask."""

    def test_task_has_validation_fields(self):
        """Test that PlanTask has all validation fields with correct defaults."""
        task = PlanTask(id="test-1", description="Test task")

        # Validation spec defaults
        assert task.validation_criteria == ""
        assert task.validation_hint == ""
        assert task.validation_timeout == 120

        # Validation state defaults
        assert task.validation_result == ""
        assert task.validation_passed is False
        assert task.validation_run_at is None

    def test_task_with_validation_criteria(self):
        """Test creating a task with validation criteria."""
        task = PlanTask(
            id="test-1",
            description="Implement feature X",
            validation_criteria="All tests in tests/test_feature.py pass",
            validation_hint="pytest tests/test_feature.py -v",
            validation_timeout=180,
        )

        assert task.validation_criteria == "All tests in tests/test_feature.py pass"
        assert task.validation_hint == "pytest tests/test_feature.py -v"
        assert task.validation_timeout == 180
        assert task.has_validation() is True

    def test_task_without_validation(self):
        """Test has_validation returns False when no criteria."""
        task = PlanTask(id="test-1", description="Test task")
        assert task.has_validation() is False

    def test_validation_to_dict(self):
        """Test that validation fields are serialized correctly."""
        now = datetime.now(timezone.utc)
        task = PlanTask(
            id="test-1",
            description="Test task",
            validation_criteria="Tests pass",
            validation_hint="pytest",
            validation_timeout=60,
            validation_result="All 10 tests passed",
            validation_passed=True,
            validation_run_at=now,
        )

        data = task.to_dict()

        assert data["validation_criteria"] == "Tests pass"
        assert data["validation_hint"] == "pytest"
        assert data["validation_timeout"] == 60
        assert data["validation_result"] == "All 10 tests passed"
        assert data["validation_passed"] is True
        assert "validation_run_at" in data

    def test_validation_to_dict_omits_defaults(self):
        """Test that default values are not included in to_dict."""
        task = PlanTask(id="test-1", description="Test task")
        data = task.to_dict()

        # These should be omitted because they're empty/default
        assert "validation_criteria" not in data
        assert "validation_hint" not in data
        assert "validation_timeout" not in data  # 120 is default
        assert "validation_result" not in data
        assert "validation_passed" not in data
        assert "validation_run_at" not in data

    def test_validation_from_dict(self):
        """Test that validation fields are deserialized correctly."""
        now = datetime.now(timezone.utc)
        data = {
            "id": "test-1",
            "description": "Test task",
            "validation_criteria": "Tests pass",
            "validation_hint": "pytest",
            "validation_timeout": 60,
            "validation_result": "All passed",
            "validation_passed": True,
            "validation_run_at": now.isoformat(),
        }

        task = PlanTask.from_dict(data)

        assert task.validation_criteria == "Tests pass"
        assert task.validation_hint == "pytest"
        assert task.validation_timeout == 60
        assert task.validation_result == "All passed"
        assert task.validation_passed is True
        assert task.validation_run_at is not None

    def test_validation_from_dict_defaults(self):
        """Test that missing validation fields get defaults."""
        data = {"id": "test-1", "description": "Test task"}
        task = PlanTask.from_dict(data)

        assert task.validation_criteria == ""
        assert task.validation_hint == ""
        assert task.validation_timeout == 120
        assert task.validation_result == ""
        assert task.validation_passed is False
        assert task.validation_run_at is None


class TestPlanTaskRequiresValidation:
    """Tests for the requires_validation method."""

    def test_implementation_task_requires_validation(self):
        """Implementation tasks require validation."""
        task = PlanTask(
            id="test-1",
            description="Test task",
            category=CATEGORY_IMPLEMENTATION,
        )
        assert task.requires_validation() is True

    def test_exploration_task_does_not_require_validation(self):
        """Exploration tasks do not require validation."""
        task = PlanTask(
            id="test-1",
            description="Test task",
            category=CATEGORY_EXPLORATION,
        )
        assert task.requires_validation() is False

    def test_default_category_requires_validation(self):
        """Default category (implementation) requires validation."""
        task = PlanTask(id="test-1", description="Test task")
        assert task.requires_validation() is True


class TestAddPlanTasksValidation:
    """Tests for add_plan_tasks validation spec parsing."""

    @pytest.fixture
    def temp_persona_dir(self, tmp_path):
        """Create a temporary persona directory."""
        persona_dir = tmp_path / "personas" / "test"
        persona_dir.mkdir(parents=True)
        return persona_dir

    @pytest.fixture
    def mock_context(self, temp_persona_dir):
        """Create a mock AgentContext."""
        context = MagicMock()
        context.session_id = "test-session-123"
        context.history_base_dir = temp_persona_dir
        context.sandbox = MagicMock()
        context.sandbox.root_directory = temp_persona_dir
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

    def test_add_task_with_validation(self, mock_context, temp_persona_dir):
        """Test adding a task with validation criteria."""
        import json
        from silica.developer.plans import PlanManager
        from silica.developer.tools.planning import add_plan_tasks

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        tasks_json = json.dumps(
            [
                {
                    "description": "Implement feature",
                    "validation": {
                        "criteria": "All tests pass",
                        "hint": "pytest tests/",
                        "timeout": 180,
                    },
                }
            ]
        )

        result = add_plan_tasks(mock_context, plan.id, tasks_json)

        assert "Added 1 tasks" in result
        assert "✓" in result  # Validation indicator

        updated = plan_manager.get_plan(plan.id)
        assert len(updated.tasks) == 1
        assert updated.tasks[0].validation_criteria == "All tests pass"
        assert updated.tasks[0].validation_hint == "pytest tests/"
        assert updated.tasks[0].validation_timeout == 180

    def test_add_task_validation_criteria_only(self, mock_context, temp_persona_dir):
        """Test adding a task with only validation criteria (no hint)."""
        import json
        from silica.developer.plans import PlanManager
        from silica.developer.tools.planning import add_plan_tasks

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        tasks_json = json.dumps(
            [
                {
                    "description": "Build project",
                    "validation": {"criteria": "npm run build succeeds"},
                }
            ]
        )

        add_plan_tasks(mock_context, plan.id, tasks_json)

        updated = plan_manager.get_plan(plan.id)
        assert updated.tasks[0].validation_criteria == "npm run build succeeds"
        assert updated.tasks[0].validation_hint == ""  # Default
        assert updated.tasks[0].validation_timeout == 120  # Default

    def test_add_task_without_validation_warns(self, mock_context, temp_persona_dir):
        """Test that implementation tasks without validation show warning."""
        import json
        from silica.developer.plans import PlanManager
        from silica.developer.tools.planning import add_plan_tasks

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        tasks_json = json.dumps(
            [
                {
                    "description": "Implement feature",
                    # No validation specified
                }
            ]
        )

        result = add_plan_tasks(mock_context, plan.id, tasks_json)

        assert "Warning" in result
        assert "without validation criteria" in result

    def test_exploration_task_no_validation_no_warning(
        self, mock_context, temp_persona_dir
    ):
        """Test that exploration tasks without validation don't warn."""
        import json
        from silica.developer.plans import PlanManager
        from silica.developer.tools.planning import add_plan_tasks

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        tasks_json = json.dumps(
            [{"description": "Research options", "category": "exploration"}]
        )

        result = add_plan_tasks(mock_context, plan.id, tasks_json)

        assert "Warning" not in result
        assert "without validation" not in result

    def test_mixed_tasks_validation_warning(self, mock_context, temp_persona_dir):
        """Test warning only counts implementation tasks without validation."""
        import json
        from silica.developer.plans import PlanManager
        from silica.developer.tools.planning import add_plan_tasks

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        tasks_json = json.dumps(
            [
                {"description": "Research", "category": "exploration"},  # No warning
                {
                    "description": "Implement A",
                    "validation": {"criteria": "Tests pass"},
                },  # Has validation
                {"description": "Implement B"},  # Missing validation - warning
            ]
        )

        result = add_plan_tasks(mock_context, plan.id, tasks_json)

        assert "1 implementation task(s) without validation" in result


class TestPlanMarkdownValidation:
    """Tests for plan markdown rendering with validation info."""

    def test_markdown_shows_validation_criteria(self):
        """Test that validation criteria appears in markdown output."""
        from silica.developer.plans import Plan, PlanStatus

        plan = Plan(
            id="test-plan",
            title="Test Plan",
            status=PlanStatus.IN_PROGRESS,
            session_id="session-123",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        plan.add_task(
            description="Test task",
            validation_criteria="All tests pass",
            validation_hint="pytest tests/",
        )

        markdown = plan.to_markdown()

        assert "Validation: All tests pass" in markdown
        assert "Hint: `pytest tests/`" in markdown

    def test_markdown_shows_validation_results(self):
        """Test that validation results appear in markdown output."""
        from silica.developer.plans import Plan, PlanStatus

        plan = Plan(
            id="test-plan",
            title="Test Plan",
            status=PlanStatus.IN_PROGRESS,
            session_id="session-123",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        task = plan.add_task(
            description="Test task",
            validation_criteria="All tests pass",
        )
        # Simulate validation run
        task.validation_passed = True
        task.validation_run_at = datetime.now(timezone.utc)
        task.validation_result = "10 tests passed in 2.5s"

        markdown = plan.to_markdown()

        assert "Last validation: ✅" in markdown
        assert "10 tests passed" in markdown

    def test_markdown_shows_failed_validation(self):
        """Test that failed validation shows ❌ indicator."""
        from silica.developer.plans import Plan, PlanStatus

        plan = Plan(
            id="test-plan",
            title="Test Plan",
            status=PlanStatus.IN_PROGRESS,
            session_id="session-123",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        task = plan.add_task(
            description="Test task",
            validation_criteria="All tests pass",
        )
        # Simulate failed validation
        task.validation_passed = False
        task.validation_run_at = datetime.now(timezone.utc)
        task.validation_result = "2 tests failed: test_foo, test_bar"

        markdown = plan.to_markdown()

        assert "Last validation: ❌" in markdown
        assert "2 tests failed" in markdown

    def test_markdown_omits_validation_if_not_set(self):
        """Test that tasks without validation don't show validation section."""
        from silica.developer.plans import Plan, PlanStatus

        plan = Plan(
            id="test-plan",
            title="Test Plan",
            status=PlanStatus.IN_PROGRESS,
            session_id="session-123",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        plan.add_task(description="Simple task")  # No validation

        markdown = plan.to_markdown()

        # Should not have validation line (but might have "Validation:" from elsewhere)
        assert "Validation: " not in markdown or "Validation: _" in markdown


class TestValidationRunner:
    """Tests for the _run_task_validation function."""

    @pytest.fixture
    def temp_persona_dir(self, tmp_path):
        """Create a temporary persona directory."""
        persona_dir = tmp_path / "personas" / "test"
        persona_dir.mkdir(parents=True)
        return persona_dir

    @pytest.fixture
    def mock_context(self, temp_persona_dir):
        """Create a mock AgentContext."""
        context = MagicMock()
        context.session_id = "test-session-123"
        context.history_base_dir = temp_persona_dir
        context.sandbox = MagicMock()
        context.sandbox.root_directory = temp_persona_dir
        context.user_interface = MagicMock()
        context.user_interface.status = MagicMock(
            return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())
        )
        context.with_user_interface = MagicMock(return_value=context)
        context.flush = MagicMock()
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

    @pytest.mark.asyncio
    async def test_validation_with_no_criteria_passes(self, mock_context):
        """Tasks without validation criteria should pass automatically."""
        from silica.developer.tools.planning import _run_task_validation

        task = PlanTask(id="test-1", description="Test task")
        # No validation_criteria set

        result = await _run_task_validation(mock_context, task)

        assert result["passed"] is True
        assert "No validation criteria" in result["reasoning"]

    @pytest.mark.asyncio
    async def test_validation_updates_task_state(self, mock_context, mocker):
        """Validation should update task's validation state fields."""
        from silica.developer.tools.planning import _run_task_validation

        task = PlanTask(
            id="test-1",
            description="Test task",
            validation_criteria="Tests pass",
            validation_hint="pytest",
        )

        # Mock the sub-agent to return a passing result
        mocker.patch(
            "silica.developer.tools.subagent.run_agent",
            new_callable=AsyncMock,
            return_value="VALIDATION_PASSED: yes\nREASONING: All tests passed\nOUTPUT: 5 passed",
        )

        result = await _run_task_validation(mock_context, task)

        assert result["passed"] is True
        assert task.validation_passed is True
        assert task.validation_run_at is not None
        assert "All tests passed" in task.validation_result

    @pytest.mark.asyncio
    async def test_validation_failure_updates_task_state(self, mock_context, mocker):
        """Failed validation should update task state with failure info."""
        from silica.developer.tools.planning import _run_task_validation

        task = PlanTask(
            id="test-1",
            description="Test task",
            validation_criteria="Tests pass",
        )

        # Mock the sub-agent to return a failing result
        mocker.patch(
            "silica.developer.tools.subagent.run_agent",
            new_callable=AsyncMock,
            return_value="VALIDATION_PASSED: no\nREASONING: 2 tests failed\nOUTPUT: FAILED test_foo, test_bar",
        )

        result = await _run_task_validation(mock_context, task)

        assert result["passed"] is False
        assert task.validation_passed is False
        assert "2 tests failed" in result["reasoning"]

    @pytest.mark.asyncio
    async def test_validation_handles_agent_error(self, mock_context, mocker):
        """Validation should handle sub-agent errors gracefully."""
        from silica.developer.tools.planning import _run_task_validation

        task = PlanTask(
            id="test-1",
            description="Test task",
            validation_criteria="Tests pass",
        )

        # Mock the sub-agent to raise an error
        mocker.patch(
            "silica.developer.tools.subagent.run_agent",
            new_callable=AsyncMock,
            side_effect=Exception("Connection failed"),
        )

        result = await _run_task_validation(mock_context, task)

        assert result["passed"] is False
        assert "error" in result["reasoning"].lower()
        assert task.validation_passed is False


class TestCompletePlanTaskValidation:
    """Tests for complete_plan_task with validation enforcement."""

    @pytest.fixture
    def temp_persona_dir(self, tmp_path):
        """Create a temporary persona directory."""
        persona_dir = tmp_path / "personas" / "test"
        persona_dir.mkdir(parents=True)
        return persona_dir

    @pytest.fixture
    def mock_context(self, temp_persona_dir):
        """Create a mock AgentContext."""
        context = MagicMock()
        context.session_id = "test-session-123"
        context.history_base_dir = temp_persona_dir
        context.sandbox = MagicMock()
        context.sandbox.root_directory = temp_persona_dir
        context.user_interface = MagicMock()
        context.user_interface.status = MagicMock(
            return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())
        )
        context.with_user_interface = MagicMock(return_value=context)
        context.flush = MagicMock()
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

    @pytest.fixture
    def plan_with_validation(self, mock_context, temp_persona_dir):
        """Create a plan with a task that has validation criteria."""
        from silica.developer.plans import PlanManager, PlanStatus

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        # Add task with validation
        plan.add_task(
            description="Implement feature",
            validation_criteria="All tests pass",
            validation_hint="pytest tests/",
        )

        # Set plan to IN_PROGRESS so completion is allowed
        plan.status = PlanStatus.IN_PROGRESS
        plan_manager.update_plan(plan)

        return plan, plan_manager

    @pytest.mark.asyncio
    async def test_complete_rejects_when_validation_fails(
        self, mock_context, plan_with_validation, mocker
    ):
        """Completion should be REJECTED if validation fails."""
        from silica.developer.tools.planning import complete_plan_task

        plan, plan_manager = plan_with_validation
        task = plan.tasks[0]

        # Mock validation to fail
        mocker.patch(
            "silica.developer.tools.subagent.run_agent",
            new_callable=AsyncMock,
            return_value="VALIDATION_PASSED: no\nREASONING: 2 tests failed\nOUTPUT: FAILED test_foo",
        )

        result = await complete_plan_task(mock_context, plan.id, task.id)

        assert "REJECTED" in result
        assert "Validation failed" in result
        assert "2 tests failed" in result

        # Task should NOT be completed
        updated_plan = plan_manager.get_plan(plan.id)
        updated_task = updated_plan.get_task_by_id(task.id)
        assert updated_task.completed is False

    @pytest.mark.asyncio
    async def test_complete_succeeds_when_validation_passes(
        self, mock_context, plan_with_validation, mocker
    ):
        """Completion should succeed if validation passes."""
        from silica.developer.tools.planning import complete_plan_task

        plan, plan_manager = plan_with_validation
        task = plan.tasks[0]

        # Mock validation to pass
        mocker.patch(
            "silica.developer.tools.subagent.run_agent",
            new_callable=AsyncMock,
            return_value="VALIDATION_PASSED: yes\nREASONING: All 10 tests pass\nOUTPUT: 10 passed",
        )

        result = await complete_plan_task(mock_context, plan.id, task.id)

        assert "completed" in result.lower()
        assert "REJECTED" not in result
        assert "Validation passed" in result

        # Task should be completed
        updated_plan = plan_manager.get_plan(plan.id)
        updated_task = updated_plan.get_task_by_id(task.id)
        assert updated_task.completed is True

    @pytest.mark.asyncio
    async def test_complete_with_skip_validation_bypasses(
        self, mock_context, plan_with_validation, mocker
    ):
        """skip_validation=True should bypass validation."""
        from silica.developer.tools.planning import complete_plan_task

        plan, plan_manager = plan_with_validation
        task = plan.tasks[0]

        # Mock should NOT be called when skipping
        mock_run_agent = mocker.patch(
            "silica.developer.tools.subagent.run_agent",
            new_callable=AsyncMock,
        )

        result = await complete_plan_task(
            mock_context, plan.id, task.id, skip_validation=True
        )

        assert "completed" in result.lower()
        assert "Warning" in result
        assert "Validation skipped" in result

        # Validation should not have been called
        mock_run_agent.assert_not_called()

        # Task should be completed despite no validation
        updated_plan = plan_manager.get_plan(plan.id)
        updated_task = updated_plan.get_task_by_id(task.id)
        assert updated_task.completed is True
        assert updated_task.validation_passed is False
        assert "skipped" in updated_task.validation_result.lower()

    @pytest.mark.asyncio
    async def test_exploration_task_skips_validation(
        self, mock_context, temp_persona_dir, mocker
    ):
        """Exploration tasks should not require validation."""
        from silica.developer.plans import (
            PlanManager,
            PlanStatus,
            CATEGORY_EXPLORATION,
        )
        from silica.developer.tools.planning import complete_plan_task

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        # Add exploration task (no validation needed)
        task = plan.add_task(
            description="Research options",
            category=CATEGORY_EXPLORATION,
        )
        plan.status = PlanStatus.IN_PROGRESS
        plan_manager.update_plan(plan)

        # Mock should NOT be called for exploration
        mock_run_agent = mocker.patch(
            "silica.developer.tools.subagent.run_agent",
            new_callable=AsyncMock,
        )

        result = await complete_plan_task(mock_context, plan.id, task.id)

        assert "completed" in result.lower()
        mock_run_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_without_validation_criteria_completes(
        self, mock_context, temp_persona_dir, mocker
    ):
        """Tasks without validation criteria should still complete (with warning at add time)."""
        from silica.developer.plans import PlanManager, PlanStatus
        from silica.developer.tools.planning import complete_plan_task

        plan_manager = PlanManager(temp_persona_dir)
        plan = plan_manager.create_plan(
            "Test Plan", "session123", root_dir=str(temp_persona_dir)
        )

        # Add task WITHOUT validation
        task = plan.add_task(description="Simple task")
        plan.status = PlanStatus.IN_PROGRESS
        plan_manager.update_plan(plan)

        # Validation should not be called if no criteria
        mock_run_agent = mocker.patch(
            "silica.developer.tools.subagent.run_agent",
            new_callable=AsyncMock,
        )

        result = await complete_plan_task(mock_context, plan.id, task.id)

        assert "completed" in result.lower()
        mock_run_agent.assert_not_called()
