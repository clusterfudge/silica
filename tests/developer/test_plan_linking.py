"""Tests for plan linking features: milestones, dependencies, subtasks, parallel execution."""

import pytest
from silica.developer.plans import Plan, PlanTask, PlanStatus, Milestone
from datetime import datetime, timezone


@pytest.fixture
def sample_plan():
    """Create a sample plan with tasks for testing."""
    plan = Plan(
        id="test-plan",
        title="Test Plan",
        status=PlanStatus.IN_PROGRESS,
        session_id="test-session",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return plan


class TestMilestone:
    """Tests for the Milestone dataclass."""

    def test_milestone_creation(self):
        m = Milestone(id="m1", title="Phase 1", description="First phase")
        assert m.id == "m1"
        assert m.title == "Phase 1"
        assert m.task_ids == []
        assert m.completed is False

    def test_milestone_to_dict(self):
        m = Milestone(id="m1", title="Phase 1", task_ids=["t1", "t2"], order=1)
        d = m.to_dict()
        assert d["id"] == "m1"
        assert d["task_ids"] == ["t1", "t2"]
        assert d["order"] == 1

    def test_milestone_from_dict(self):
        d = {"id": "m1", "title": "Phase 1", "task_ids": ["t1"], "completed": True}
        m = Milestone.from_dict(d)
        assert m.id == "m1"
        assert m.task_ids == ["t1"]
        assert m.completed is True


class TestPlanTaskSubtasks:
    """Tests for subtask support in PlanTask."""

    def test_task_parent_id_default_none(self):
        task = PlanTask(id="t1", description="Task 1")
        assert task.parent_task_id is None

    def test_task_with_parent(self):
        task = PlanTask(id="t1", description="Subtask", parent_task_id="parent1")
        assert task.parent_task_id == "parent1"

    def test_task_to_dict_excludes_none_parent(self):
        task = PlanTask(id="t1", description="Task 1")
        d = task.to_dict()
        assert "parent_task_id" not in d

    def test_task_to_dict_includes_parent_when_set(self):
        task = PlanTask(id="t1", description="Subtask", parent_task_id="p1")
        d = task.to_dict()
        assert d["parent_task_id"] == "p1"


class TestDependencyMethods:
    """Tests for dependency-aware task methods."""

    def test_is_task_ready_no_deps(self, sample_plan):
        sample_plan.tasks = [PlanTask(id="t1", description="Task 1")]
        assert sample_plan.is_task_ready("t1") is True

    def test_is_task_ready_with_completed_dep(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1", completed=True),
            PlanTask(id="t2", description="Task 2", dependencies=["t1"]),
        ]
        assert sample_plan.is_task_ready("t2") is True

    def test_is_task_ready_with_incomplete_dep(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1", completed=False),
            PlanTask(id="t2", description="Task 2", dependencies=["t1"]),
        ]
        assert sample_plan.is_task_ready("t2") is False

    def test_get_blocking_tasks(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1"),
            PlanTask(id="t2", description="Task 2", dependencies=["t1"]),
        ]
        blocking = sample_plan.get_blocking_tasks("t2")
        assert len(blocking) == 1
        assert blocking[0].id == "t1"

    def test_get_ready_tasks(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1"),
            PlanTask(id="t2", description="Task 2", dependencies=["t1"]),
            PlanTask(id="t3", description="Task 3"),
        ]
        ready = sample_plan.get_ready_tasks()
        assert len(ready) == 2
        assert {t.id for t in ready} == {"t1", "t3"}

    def test_get_blocked_tasks(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1"),
            PlanTask(id="t2", description="Task 2", dependencies=["t1"]),
        ]
        blocked = sample_plan.get_blocked_tasks()
        assert len(blocked) == 1
        assert blocked[0].id == "t2"


class TestParallelExecution:
    """Tests for parallel task detection."""

    def test_can_run_parallel_no_overlap(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1", files=["a.py"]),
            PlanTask(id="t2", description="Task 2", files=["b.py"]),
        ]
        assert sample_plan.can_run_parallel("t1", "t2") is True

    def test_can_run_parallel_with_overlap(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1", files=["a.py"]),
            PlanTask(id="t2", description="Task 2", files=["a.py"]),
        ]
        assert sample_plan.can_run_parallel("t1", "t2") is False

    def test_can_run_parallel_with_dependency(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1"),
            PlanTask(id="t2", description="Task 2", dependencies=["t1"]),
        ]
        assert sample_plan.can_run_parallel("t1", "t2") is False

    def test_get_max_parallel_tasks(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1", files=["a.py"]),
            PlanTask(id="t2", description="Task 2", files=["b.py"]),
            PlanTask(id="t3", description="Task 3", files=["c.py"]),
        ]
        parallel = sample_plan.get_max_parallel_tasks()
        assert len(parallel) == 3


class TestSubtaskMethods:
    """Tests for subtask helper methods."""

    def test_get_subtasks(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Parent"),
            PlanTask(id="t1a", description="Child 1", parent_task_id="t1"),
            PlanTask(id="t1b", description="Child 2", parent_task_id="t1"),
        ]
        subtasks = sample_plan.get_subtasks("t1")
        assert len(subtasks) == 2

    def test_is_container_task(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Parent"),
            PlanTask(id="t1a", description="Child", parent_task_id="t1"),
        ]
        assert sample_plan.is_container_task("t1") is True
        assert sample_plan.is_container_task("t1a") is False

    def test_are_all_subtasks_complete(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Parent"),
            PlanTask(
                id="t1a", description="Child 1", parent_task_id="t1", completed=True
            ),
            PlanTask(
                id="t1b", description="Child 2", parent_task_id="t1", completed=False
            ),
        ]
        assert sample_plan.are_all_subtasks_complete("t1") is False
        sample_plan.tasks[2].completed = True
        assert sample_plan.are_all_subtasks_complete("t1") is True


class TestCircularDependency:
    """Tests for circular dependency detection."""

    def test_no_cycle(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1"),
            PlanTask(id="t2", description="Task 2", dependencies=["t1"]),
            PlanTask(id="t3", description="Task 3", dependencies=["t2"]),
        ]
        assert sample_plan.has_dependency_cycle() is False

    def test_simple_cycle(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1", dependencies=["t2"]),
            PlanTask(id="t2", description="Task 2", dependencies=["t1"]),
        ]
        assert sample_plan.has_dependency_cycle() is True

    def test_would_create_cycle(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1"),
            PlanTask(id="t2", description="Task 2", dependencies=["t1"]),
        ]
        # Adding t1 -> t2 would create cycle since t2 -> t1 exists
        assert sample_plan.would_create_cycle("t1", "t2") is True
        # Adding t3 -> t1 would not create cycle
        sample_plan.tasks.append(PlanTask(id="t3", description="Task 3"))
        assert sample_plan.would_create_cycle("t3", "t1") is False

    def test_validate_dependencies(self, sample_plan):
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1", dependencies=["t1"]),  # self-dep
            PlanTask(id="t2", description="Task 2", dependencies=["nonexistent"]),
        ]
        errors = sample_plan.validate_dependencies()
        # 3 errors: cycle (self-dep creates cycle), self-dep, nonexistent
        assert len(errors) == 3
        assert any("self-dependency" in e for e in errors)
        assert any("non-existent" in e for e in errors)
        assert any("Circular" in e for e in errors)


class TestPlanningTools:
    """Tests for planning tools: milestone, dependency, subtask management."""

    def test_add_milestone_tool(self, sample_plan, tmp_path):
        """Test add_milestone tool."""
        from unittest.mock import MagicMock
        from silica.developer.tools.planning import add_milestone

        ctx = MagicMock()
        ctx.history_base_dir = tmp_path
        ctx.sandbox = MagicMock()
        ctx.sandbox.root_directory = tmp_path

        # Save plan first
        from silica.developer.plans import PlanManager

        pm = PlanManager(tmp_path)
        pm.plans_dir.mkdir(parents=True, exist_ok=True)
        pm.update_plan(sample_plan)

        result = add_milestone(ctx, sample_plan.id, "Phase 1", "First phase")
        assert "Added milestone" in result
        assert "Phase 1" in result

    def test_add_task_dependency_tool(self, sample_plan, tmp_path):
        """Test add_task_dependency tool."""
        from unittest.mock import MagicMock
        from silica.developer.tools.planning import add_task_dependency
        from silica.developer.plans import PlanManager

        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1"),
            PlanTask(id="t2", description="Task 2"),
        ]

        ctx = MagicMock()
        ctx.history_base_dir = tmp_path
        ctx.sandbox = MagicMock()
        ctx.sandbox.root_directory = tmp_path

        pm = PlanManager(tmp_path)
        pm.plans_dir.mkdir(parents=True, exist_ok=True)
        pm.update_plan(sample_plan)

        result = add_task_dependency(ctx, sample_plan.id, "t2", "t1")
        assert "depends on" in result

    def test_add_task_dependency_cycle_detection(self, sample_plan, tmp_path):
        """Test that adding a cyclic dependency is rejected."""
        from unittest.mock import MagicMock
        from silica.developer.tools.planning import add_task_dependency
        from silica.developer.plans import PlanManager

        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1", dependencies=["t2"]),
            PlanTask(id="t2", description="Task 2"),
        ]

        ctx = MagicMock()
        ctx.history_base_dir = tmp_path
        ctx.sandbox = MagicMock()
        ctx.sandbox.root_directory = tmp_path

        pm = PlanManager(tmp_path)
        pm.plans_dir.mkdir(parents=True, exist_ok=True)
        pm.update_plan(sample_plan)

        result = add_task_dependency(ctx, sample_plan.id, "t2", "t1")
        assert "cycle" in result.lower()

    def test_get_ready_tasks_tool(self, sample_plan, tmp_path):
        """Test get_ready_tasks tool."""
        from unittest.mock import MagicMock
        from silica.developer.tools.planning import get_ready_tasks
        from silica.developer.plans import PlanManager

        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1"),
            PlanTask(id="t2", description="Task 2", dependencies=["t1"]),
            PlanTask(id="t3", description="Task 3"),
        ]

        ctx = MagicMock()
        ctx.history_base_dir = tmp_path
        ctx.sandbox = MagicMock()
        ctx.sandbox.root_directory = tmp_path

        pm = PlanManager(tmp_path)
        pm.plans_dir.mkdir(parents=True, exist_ok=True)
        pm.update_plan(sample_plan)

        result = get_ready_tasks(ctx, sample_plan.id)
        assert "t1" in result
        assert "t3" in result
        assert "Blocked" in result
        assert "t2" in result

    def test_expand_task_tool(self, sample_plan, tmp_path):
        """Test expand_task tool."""
        from unittest.mock import MagicMock
        from silica.developer.tools.planning import expand_task
        from silica.developer.plans import PlanManager

        sample_plan.tasks = [PlanTask(id="t1", description="Parent task")]

        ctx = MagicMock()
        ctx.history_base_dir = tmp_path
        ctx.sandbox = MagicMock()
        ctx.sandbox.root_directory = tmp_path

        pm = PlanManager(tmp_path)
        pm.plans_dir.mkdir(parents=True, exist_ok=True)
        pm.update_plan(sample_plan)

        result = expand_task(ctx, sample_plan.id, "t1", '["Subtask 1", "Subtask 2"]')
        assert "Added 2 subtasks" in result


class TestBehavioralChanges:
    """Tests for behavioral changes: ephemeral state, status info."""

    def test_get_ephemeral_plan_state_shows_ready_tasks(self, sample_plan, tmp_path):
        """Test that ephemeral state shows ready tasks."""
        from unittest.mock import MagicMock
        from silica.developer.tools.planning import get_ephemeral_plan_state
        from silica.developer.plans import PlanManager

        sample_plan.status = PlanStatus.IN_PROGRESS
        sample_plan.tasks = [
            PlanTask(id="t1", description="Ready task 1"),
            PlanTask(id="t2", description="Blocked task", dependencies=["t1"]),
        ]

        ctx = MagicMock()
        ctx.active_plan_id = sample_plan.id
        ctx.history_base_dir = tmp_path
        ctx.sandbox = MagicMock()
        ctx.sandbox.root_directory = tmp_path

        pm = PlanManager(tmp_path)
        pm.plans_dir.mkdir(parents=True, exist_ok=True)
        pm.update_plan(sample_plan)

        result = get_ephemeral_plan_state(ctx)
        assert "Ready Tasks" in result
        assert "t1" in result

    def test_get_ephemeral_plan_state_shows_blocked_tasks(self, sample_plan, tmp_path):
        """Test that ephemeral state shows blocked tasks."""
        from unittest.mock import MagicMock
        from silica.developer.tools.planning import get_ephemeral_plan_state
        from silica.developer.plans import PlanManager

        sample_plan.status = PlanStatus.IN_PROGRESS
        sample_plan.tasks = [
            PlanTask(id="t1", description="Blocker"),
            PlanTask(id="t2", description="Blocked", dependencies=["t1"]),
        ]

        ctx = MagicMock()
        ctx.active_plan_id = sample_plan.id
        ctx.history_base_dir = tmp_path
        ctx.sandbox = MagicMock()
        ctx.sandbox.root_directory = tmp_path

        pm = PlanManager(tmp_path)
        pm.plans_dir.mkdir(parents=True, exist_ok=True)
        pm.update_plan(sample_plan)

        result = get_ephemeral_plan_state(ctx)
        assert "Blocked" in result
        assert "t2" in result

    def test_get_active_plan_status_includes_ready_count(self, sample_plan, tmp_path):
        """Test that status includes ready task count."""
        from unittest.mock import MagicMock
        from silica.developer.tools.planning import get_active_plan_status
        from silica.developer.plans import PlanManager

        sample_plan.status = PlanStatus.IN_PROGRESS
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1"),
            PlanTask(id="t2", description="Task 2"),
        ]

        ctx = MagicMock()
        ctx.active_plan_id = sample_plan.id
        ctx.history_base_dir = tmp_path
        ctx.sandbox = MagicMock()
        ctx.sandbox.root_directory = tmp_path

        pm = PlanManager(tmp_path)
        pm.plans_dir.mkdir(parents=True, exist_ok=True)
        pm.update_plan(sample_plan)

        status = get_active_plan_status(ctx)
        assert status["ready_tasks"] == 2
        assert status["blocked_tasks"] == 0


class TestPlanMilestones:
    """Tests for milestone field on Plan."""

    def test_plan_with_milestones(self, sample_plan):
        sample_plan.milestones = [
            Milestone(id="m1", title="Phase 1", task_ids=["t1", "t2"]),
        ]
        sample_plan.tasks = [
            PlanTask(id="t1", description="Task 1"),
            PlanTask(id="t2", description="Task 2"),
        ]
        assert len(sample_plan.milestones) == 1
        assert sample_plan.milestones[0].task_ids == ["t1", "t2"]

    def test_plan_to_dict_includes_milestones(self, sample_plan):
        sample_plan.milestones = [Milestone(id="m1", title="Phase 1")]
        d = sample_plan.to_dict()
        assert "milestones" in d
        assert len(d["milestones"]) == 1

    def test_plan_from_dict_with_milestones(self):
        d = {
            "id": "p1",
            "title": "Test",
            "status": "draft",
            "session_id": "s1",
            "milestones": [{"id": "m1", "title": "Phase 1"}],
        }
        plan = Plan.from_dict(d)
        assert len(plan.milestones) == 1
        assert plan.milestones[0].title == "Phase 1"
