"""Tests for the Plan Mode core infrastructure."""

import pytest
from datetime import datetime, timezone

from silica.developer.plans import (
    Plan,
    PlanTask,
    PlanStatus,
    PlanManager,
    ClarificationQuestion,
)


class TestPlanTask:
    """Tests for PlanTask dataclass."""

    def test_create_task(self):
        task = PlanTask(
            id="task1",
            description="Implement feature X",
            details="Add the new endpoint",
            files=["api.py", "tests.py"],
            tests="Unit tests for endpoint",
        )
        assert task.id == "task1"
        assert task.description == "Implement feature X"
        assert task.completed is False

    def test_task_to_dict(self):
        task = PlanTask(
            id="task1",
            description="Test task",
            files=["file.py"],
        )
        data = task.to_dict()
        assert data["id"] == "task1"
        assert data["description"] == "Test task"
        assert data["files"] == ["file.py"]
        assert data["completed"] is False

    def test_task_from_dict(self):
        data = {
            "id": "task2",
            "description": "From dict task",
            "completed": True,
            "dependencies": ["task1"],
        }
        task = PlanTask.from_dict(data)
        assert task.id == "task2"
        assert task.completed is True
        assert task.dependencies == ["task1"]


class TestClarificationQuestion:
    """Tests for ClarificationQuestion dataclass."""

    def test_create_question(self):
        q = ClarificationQuestion(
            id="q1",
            question="What auth method?",
            question_type="choice",
            options=["JWT", "OAuth"],
        )
        assert q.id == "q1"
        assert q.question_type == "choice"
        assert q.answer is None

    def test_question_with_answer(self):
        q = ClarificationQuestion(
            id="q1",
            question="Test?",
            answer="Yes",
            answered_at=datetime.now(timezone.utc),
        )
        data = q.to_dict()
        assert data["answer"] == "Yes"
        assert "answered_at" in data

    def test_question_from_dict(self):
        data = {
            "id": "q2",
            "question": "Choose one",
            "type": "choice",
            "options": ["A", "B", "C"],
            "answer": "B",
        }
        q = ClarificationQuestion.from_dict(data)
        assert q.question_type == "choice"
        assert q.options == ["A", "B", "C"]
        assert q.answer == "B"


class TestPlan:
    """Tests for Plan dataclass."""

    def test_create_plan(self):
        now = datetime.now(timezone.utc)
        plan = Plan(
            id="plan1",
            title="Test Plan",
            status=PlanStatus.DRAFT,
            session_id="session123",
            created_at=now,
            updated_at=now,
        )
        assert plan.id == "plan1"
        assert plan.title == "Test Plan"
        assert plan.status == PlanStatus.DRAFT

    def test_plan_to_dict(self):
        now = datetime.now(timezone.utc)
        plan = Plan(
            id="plan1",
            title="Test Plan",
            status=PlanStatus.DRAFT,
            session_id="session123",
            created_at=now,
            updated_at=now,
            context="Test context",
        )
        data = plan.to_dict()
        assert data["id"] == "plan1"
        assert data["status"] == "draft"
        assert data["context"] == "Test context"

    def test_plan_from_dict(self):
        data = {
            "id": "plan2",
            "title": "From Dict Plan",
            "status": "in-review",
            "session_id": "sess456",
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-02T00:00:00+00:00",
        }
        plan = Plan.from_dict(data)
        assert plan.id == "plan2"
        assert plan.status == PlanStatus.IN_REVIEW

    def test_plan_to_markdown(self):
        now = datetime.now(timezone.utc)
        plan = Plan(
            id="plan1",
            title="My Test Plan",
            status=PlanStatus.DRAFT,
            session_id="session123",
            created_at=now,
            updated_at=now,
            context="This is the context",
            approach="This is the approach",
        )

        md = plan.to_markdown()
        assert "# Plan: My Test Plan" in md
        assert "**ID:** plan1" in md
        assert "**Status:** draft" in md
        assert "This is the context" in md
        assert "This is the approach" in md
        assert "<!-- plan-data" in md

    def test_plan_from_markdown_with_json(self):
        now = datetime.now(timezone.utc)
        original = Plan(
            id="plan1",
            title="Round Trip Plan",
            status=PlanStatus.APPROVED,
            session_id="session123",
            created_at=now,
            updated_at=now,
            context="Test context",
            approach="Test approach",
        )
        original.add_task("Task 1", details="Do something")
        original.add_question("What color?", "choice", ["Red", "Blue"])

        md = original.to_markdown()
        restored = Plan.from_markdown(md)

        assert restored.id == original.id
        assert restored.title == original.title
        assert restored.status == original.status
        assert len(restored.tasks) == 1
        assert len(restored.questions) == 1

    def test_plan_add_task(self):
        now = datetime.now(timezone.utc)
        plan = Plan(
            id="plan1",
            title="Test",
            status=PlanStatus.DRAFT,
            session_id="sess",
            created_at=now,
            updated_at=now,
        )

        task = plan.add_task("New task", details="Task details")
        assert len(plan.tasks) == 1
        assert task.description == "New task"
        assert task.id is not None

    def test_plan_add_question(self):
        now = datetime.now(timezone.utc)
        plan = Plan(
            id="plan1",
            title="Test",
            status=PlanStatus.DRAFT,
            session_id="sess",
            created_at=now,
            updated_at=now,
        )

        q = plan.add_question("What method?", "choice", ["A", "B"])
        assert len(plan.questions) == 1
        assert q.question == "What method?"
        assert q.options == ["A", "B"]

    def test_plan_answer_question(self):
        now = datetime.now(timezone.utc)
        plan = Plan(
            id="plan1",
            title="Test",
            status=PlanStatus.DRAFT,
            session_id="sess",
            created_at=now,
            updated_at=now,
        )
        q = plan.add_question("Test question?")

        result = plan.answer_question(q.id, "The answer")
        assert result is True
        assert plan.questions[0].answer == "The answer"
        assert plan.questions[0].answered_at is not None

    def test_plan_complete_task(self):
        now = datetime.now(timezone.utc)
        plan = Plan(
            id="plan1",
            title="Test",
            status=PlanStatus.DRAFT,
            session_id="sess",
            created_at=now,
            updated_at=now,
        )
        task = plan.add_task("Task to complete")

        result = plan.complete_task(task.id)
        assert result is True
        assert plan.tasks[0].completed is True

    def test_plan_get_unanswered_questions(self):
        now = datetime.now(timezone.utc)
        plan = Plan(
            id="plan1",
            title="Test",
            status=PlanStatus.DRAFT,
            session_id="sess",
            created_at=now,
            updated_at=now,
        )
        q1 = plan.add_question("Question 1")
        q2 = plan.add_question("Question 2")
        plan.answer_question(q1.id, "Answer 1")

        unanswered = plan.get_unanswered_questions()
        assert len(unanswered) == 1
        assert unanswered[0].id == q2.id

    def test_plan_add_progress(self):
        now = datetime.now(timezone.utc)
        plan = Plan(
            id="plan1",
            title="Test",
            status=PlanStatus.DRAFT,
            session_id="sess",
            created_at=now,
            updated_at=now,
        )

        plan.add_progress("Started working")
        assert len(plan.progress_log) == 1
        assert plan.progress_log[0].message == "Started working"


class TestPlanManager:
    """Tests for PlanManager class."""

    @pytest.fixture
    def temp_persona_dir(self, tmp_path):
        """Create a temporary persona directory."""
        persona_dir = tmp_path / "personas" / "test"
        persona_dir.mkdir(parents=True)
        return persona_dir

    @pytest.fixture
    def plan_manager(self, temp_persona_dir):
        """Create a PlanManager with temporary directory."""
        return PlanManager(temp_persona_dir)

    def test_create_plan_manager(self, temp_persona_dir):
        manager = PlanManager(temp_persona_dir)
        assert manager.active_dir.exists()
        assert manager.completed_dir.exists()

    def test_create_plan(self, plan_manager):
        plan = plan_manager.create_plan(
            title="Test Plan",
            session_id="session123",
            context="Test context",
        )

        assert plan.id is not None
        assert plan.title == "Test Plan"
        assert plan.status == PlanStatus.DRAFT
        assert len(plan.progress_log) == 1  # Created message

        # Check file was created
        plan_file = plan_manager.active_dir / f"{plan.id}.md"
        assert plan_file.exists()

    def test_get_plan(self, plan_manager):
        created = plan_manager.create_plan("Test", "sess123")

        retrieved = plan_manager.get_plan(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.title == "Test"

    def test_get_nonexistent_plan(self, plan_manager):
        result = plan_manager.get_plan("nonexistent")
        assert result is None

    def test_update_plan(self, plan_manager):
        plan = plan_manager.create_plan("Test", "sess123")
        original_updated = plan.updated_at

        plan.context = "Updated context"
        plan_manager.update_plan(plan)

        retrieved = plan_manager.get_plan(plan.id)
        assert retrieved.context == "Updated context"
        assert retrieved.updated_at >= original_updated

    def test_list_active_plans(self, plan_manager):
        plan_manager.create_plan("Plan 1", "sess1")
        plan2 = plan_manager.create_plan("Plan 2", "sess2")

        active = plan_manager.list_active_plans()
        assert len(active) == 2
        # Should be sorted by updated_at, newest first
        assert active[0].id == plan2.id

    def test_submit_for_review(self, plan_manager):
        plan = plan_manager.create_plan("Test", "sess123")

        result = plan_manager.submit_for_review(plan.id)
        assert result is True

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.IN_REVIEW

    def test_submit_for_review_wrong_status(self, plan_manager):
        plan = plan_manager.create_plan("Test", "sess123")
        plan_manager.submit_for_review(plan.id)

        # Try to submit again (already in review)
        result = plan_manager.submit_for_review(plan.id)
        assert result is False

    def test_approve_plan(self, plan_manager):
        plan = plan_manager.create_plan("Test", "sess123")
        plan_manager.submit_for_review(plan.id)

        result = plan_manager.approve_plan(plan.id)
        assert result is True

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.APPROVED

    def test_approve_plan_wrong_status(self, plan_manager):
        plan = plan_manager.create_plan("Test", "sess123")
        # Try to approve without submitting for review
        result = plan_manager.approve_plan(plan.id)
        assert result is False

    def test_start_execution(self, plan_manager):
        plan = plan_manager.create_plan("Test", "sess123")
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)

        result = plan_manager.start_execution(plan.id)
        assert result is True

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.IN_PROGRESS

    def test_complete_plan(self, plan_manager):
        plan = plan_manager.create_plan("Test", "sess123")
        plan_manager.submit_for_review(plan.id)
        plan_manager.approve_plan(plan.id)
        plan_manager.start_execution(plan.id)

        result = plan_manager.complete_plan(plan.id, "All done!")
        assert result is True

        # Should be moved to completed directory
        active_file = plan_manager.active_dir / f"{plan.id}.md"
        completed_file = plan_manager.completed_dir / f"{plan.id}.md"
        assert not active_file.exists()
        assert completed_file.exists()

        # Should still be retrievable
        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.COMPLETED
        assert updated.completion_notes == "All done!"

    def test_abandon_plan(self, plan_manager):
        plan = plan_manager.create_plan("Test", "sess123")

        result = plan_manager.abandon_plan(plan.id, "Changed requirements")
        assert result is True

        # Should be moved to completed directory
        active_file = plan_manager.active_dir / f"{plan.id}.md"
        completed_file = plan_manager.completed_dir / f"{plan.id}.md"
        assert not active_file.exists()
        assert completed_file.exists()

        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.ABANDONED

    def test_list_completed_plans(self, plan_manager):
        plan1 = plan_manager.create_plan("Plan 1", "sess1")
        plan2 = plan_manager.create_plan("Plan 2", "sess2")

        # Complete one, abandon one
        plan_manager.submit_for_review(plan1.id)
        plan_manager.approve_plan(plan1.id)
        plan_manager.complete_plan(plan1.id)
        plan_manager.abandon_plan(plan2.id)

        completed = plan_manager.list_completed_plans()
        assert len(completed) == 2

    def test_full_plan_lifecycle(self, plan_manager):
        """Test a complete plan lifecycle from creation to completion."""
        # Create
        plan = plan_manager.create_plan(
            title="Implement Feature X",
            session_id="sess123",
            context="We need to add a new feature",
        )
        assert plan.status == PlanStatus.DRAFT

        # Add content
        plan.approach = "We'll implement it in three phases"
        plan.add_task("Phase 1: Setup", files=["setup.py"])
        plan.add_task("Phase 2: Implementation", files=["main.py"])
        plan.add_task("Phase 3: Testing", files=["test_main.py"])
        q = plan.add_question("Use async?", "choice", ["Yes", "No"])
        plan_manager.update_plan(plan)

        # Answer question
        plan.answer_question(q.id, "Yes")
        plan_manager.update_plan(plan)

        # Submit for review
        plan_manager.submit_for_review(plan.id)
        assert plan_manager.get_plan(plan.id).status == PlanStatus.IN_REVIEW

        # Approve
        plan_manager.approve_plan(plan.id)
        assert plan_manager.get_plan(plan.id).status == PlanStatus.APPROVED

        # Start execution
        plan_manager.start_execution(plan.id)
        updated = plan_manager.get_plan(plan.id)
        assert updated.status == PlanStatus.IN_PROGRESS

        # Complete tasks
        for task in updated.tasks:
            updated.complete_task(task.id)
        plan_manager.update_plan(updated)

        # Complete plan
        plan_manager.complete_plan(plan.id, "Feature X implemented successfully!")

        final = plan_manager.get_plan(plan.id)
        assert final.status == PlanStatus.COMPLETED
        assert all(t.completed for t in final.tasks)
        assert final.completion_notes == "Feature X implemented successfully!"
