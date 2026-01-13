"""Plan Mode - Structured planning workflow for complex changes.

This module provides the core infrastructure for plan mode, including:
- Plan data model with serialization to/from markdown
- PlanManager for CRUD operations on plans
- Plan status lifecycle management
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional
import json
import re
import uuid


class PlanStatus(Enum):
    """Status of a plan in its lifecycle."""

    DRAFT = "draft"
    IN_REVIEW = "in-review"
    APPROVED = "approved"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


@dataclass
class PlanTask:
    """A single task within a plan.

    Tasks have two states:
    - completed: Code/implementation is done
    - verified: Tests pass and changes are validated
    """

    id: str
    description: str
    details: str = ""
    files: list[str] = field(default_factory=list)
    tests: str = ""
    dependencies: list[str] = field(default_factory=list)
    completed: bool = False
    verified: bool = False
    verification_notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "details": self.details,
            "files": self.files,
            "tests": self.tests,
            "dependencies": self.dependencies,
            "completed": self.completed,
            "verified": self.verified,
            "verification_notes": self.verification_notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanTask":
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            description=data.get("description", ""),
            details=data.get("details", ""),
            files=data.get("files", []),
            tests=data.get("tests", ""),
            dependencies=data.get("dependencies", []),
            completed=data.get("completed", False),
            verified=data.get("verified", False),
            verification_notes=data.get("verification_notes", ""),
        )


@dataclass
class ClarificationQuestion:
    """A clarifying question asked during planning."""

    id: str
    question: str
    question_type: str = "text"  # text, choice, multi_choice
    options: list[str] = field(default_factory=list)
    required: bool = True
    answer: Optional[str] = None
    answered_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "question": self.question,
            "type": self.question_type,
            "options": self.options,
            "required": self.required,
        }
        if self.answer is not None:
            result["answer"] = self.answer
        if self.answered_at is not None:
            result["answered_at"] = self.answered_at.isoformat()
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "ClarificationQuestion":
        answered_at = None
        if data.get("answered_at"):
            try:
                answered_at = datetime.fromisoformat(
                    data["answered_at"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            question=data.get("question", ""),
            question_type=data.get("type", "text"),
            options=data.get("options", []),
            required=data.get("required", True),
            answer=data.get("answer"),
            answered_at=answered_at,
        )


@dataclass
class ProgressEntry:
    """A progress log entry."""

    timestamp: datetime
    message: str

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProgressEntry":
        timestamp = datetime.now(timezone.utc)
        if data.get("timestamp"):
            try:
                timestamp = datetime.fromisoformat(
                    data["timestamp"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass
        return cls(timestamp=timestamp, message=data.get("message", ""))


@dataclass
class Plan:
    """A structured plan for complex changes."""

    id: str
    title: str
    status: PlanStatus
    session_id: str
    created_at: datetime
    updated_at: datetime
    root_dir: str = ""  # Project root directory this plan belongs to
    context: str = ""
    approach: str = ""
    tasks: list[PlanTask] = field(default_factory=list)
    questions: list[ClarificationQuestion] = field(default_factory=list)
    considerations: dict[str, str] = field(default_factory=dict)
    progress_log: list[ProgressEntry] = field(default_factory=list)
    completion_notes: str = ""

    def to_dict(self) -> dict:
        """Convert plan to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "root_dir": self.root_dir,
            "context": self.context,
            "approach": self.approach,
            "tasks": [t.to_dict() for t in self.tasks],
            "questions": [q.to_dict() for q in self.questions],
            "considerations": self.considerations,
            "progress_log": [p.to_dict() for p in self.progress_log],
            "completion_notes": self.completion_notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Plan":
        """Create plan from dictionary."""
        created_at = datetime.now(timezone.utc)
        updated_at = datetime.now(timezone.utc)

        if data.get("created_at"):
            try:
                created_at = datetime.fromisoformat(
                    data["created_at"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        if data.get("updated_at"):
            try:
                updated_at = datetime.fromisoformat(
                    data["updated_at"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            title=data.get("title", "Untitled Plan"),
            status=PlanStatus(data.get("status", "draft")),
            session_id=data.get("session_id", ""),
            created_at=created_at,
            updated_at=updated_at,
            root_dir=data.get("root_dir", ""),
            context=data.get("context", ""),
            approach=data.get("approach", ""),
            tasks=[PlanTask.from_dict(t) for t in data.get("tasks", [])],
            questions=[
                ClarificationQuestion.from_dict(q) for q in data.get("questions", [])
            ],
            considerations=data.get("considerations", {}),
            progress_log=[
                ProgressEntry.from_dict(p) for p in data.get("progress_log", [])
            ],
            completion_notes=data.get("completion_notes", ""),
        )

    def to_markdown(self) -> str:
        """Render plan as markdown document."""
        lines = []

        # Header
        lines.append(f"# Plan: {self.title}")
        lines.append("")
        lines.append(f"**ID:** {self.id}")
        lines.append(
            f"**Created:** {self.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        lines.append(
            f"**Updated:** {self.updated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        lines.append(f"**Status:** {self.status.value}")
        lines.append(f"**Session:** {self.session_id}")
        lines.append("")

        # Context
        lines.append("## Context")
        lines.append("")
        lines.append(self.context if self.context else "_No context provided yet._")
        lines.append("")

        # Questions and Answers
        if self.questions:
            lines.append("## Clarification Questions")
            lines.append("")
            for q in self.questions:
                checkbox = "[x]" if q.answer else "[ ]"
                lines.append(f"- {checkbox} **{q.question}**")
                if q.options:
                    lines.append(f"  - Options: {', '.join(q.options)}")
                if q.answer:
                    lines.append(f"  - **Answer:** {q.answer}")
                lines.append("")

        # Approach
        lines.append("## Implementation Approach")
        lines.append("")
        lines.append(self.approach if self.approach else "_No approach defined yet._")
        lines.append("")

        # Tasks
        lines.append("## Tasks")
        lines.append("")
        if self.tasks:
            for task in self.tasks:
                # Show status: ⬜ pending, ✅ completed, ✓✓ verified
                if task.verified:
                    status = "✓✓"
                elif task.completed:
                    status = "✅"
                else:
                    status = "⬜"
                lines.append(f"- {status} **{task.description}** (id: {task.id})")
                if task.details:
                    lines.append(f"  - Details: {task.details}")
                if task.files:
                    lines.append(f"  - Files: {', '.join(task.files)}")
                if task.tests:
                    lines.append(f"  - Tests: {task.tests}")
                if task.dependencies:
                    lines.append(f"  - Dependencies: {', '.join(task.dependencies)}")
                if task.verification_notes:
                    lines.append(f"  - Verification: {task.verification_notes}")
                lines.append("")
        else:
            lines.append("_No tasks defined yet._")
            lines.append("")

        # Considerations
        lines.append("## Considerations")
        lines.append("")
        if self.considerations:
            for key, value in self.considerations.items():
                lines.append(f"- **{key}:** {value}")
            lines.append("")
        else:
            lines.append("_No considerations noted yet._")
            lines.append("")

        # Progress Log
        if self.progress_log:
            lines.append("## Progress Log")
            lines.append("")
            for entry in self.progress_log:
                timestamp = entry.timestamp.strftime("%Y-%m-%d %H:%M")
                lines.append(f"- [{timestamp}] {entry.message}")
            lines.append("")

        # Completion Notes
        if self.completion_notes:
            lines.append("## Completion Notes")
            lines.append("")
            lines.append(self.completion_notes)
            lines.append("")

        # JSON data block for round-trip parsing
        lines.append("---")
        lines.append("")
        lines.append("<!-- plan-data")
        lines.append(json.dumps(self.to_dict(), indent=2))
        lines.append("-->")

        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, content: str) -> "Plan":
        """Parse plan from markdown document.

        Looks for embedded JSON data block first, falls back to parsing markdown.
        """
        # Try to extract JSON data block
        json_match = re.search(r"<!-- plan-data\s*\n(.*?)\n-->", content, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return cls.from_dict(data)
            except json.JSONDecodeError:
                pass

        # Fallback: parse markdown (basic extraction)
        plan_data = {
            "id": "",
            "title": "Untitled Plan",
            "status": "draft",
            "session_id": "",
            "context": "",
            "approach": "",
        }

        # Extract title
        title_match = re.search(r"^# Plan: (.+)$", content, re.MULTILINE)
        if title_match:
            plan_data["title"] = title_match.group(1).strip()

        # Extract metadata
        id_match = re.search(r"\*\*ID:\*\* (.+)$", content, re.MULTILINE)
        if id_match:
            plan_data["id"] = id_match.group(1).strip()

        status_match = re.search(r"\*\*Status:\*\* (.+)$", content, re.MULTILINE)
        if status_match:
            plan_data["status"] = status_match.group(1).strip()

        session_match = re.search(r"\*\*Session:\*\* (.+)$", content, re.MULTILINE)
        if session_match:
            plan_data["session_id"] = session_match.group(1).strip()

        # Extract sections (basic)
        context_match = re.search(
            r"## Context\s*\n\n(.*?)(?=\n##|\n---|\Z)", content, re.DOTALL
        )
        if context_match:
            ctx = context_match.group(1).strip()
            if ctx != "_No context provided yet._":
                plan_data["context"] = ctx

        approach_match = re.search(
            r"## Implementation Approach\s*\n\n(.*?)(?=\n##|\n---|\Z)",
            content,
            re.DOTALL,
        )
        if approach_match:
            approach = approach_match.group(1).strip()
            if approach != "_No approach defined yet._":
                plan_data["approach"] = approach

        return cls.from_dict(plan_data)

    def add_progress(self, message: str) -> None:
        """Add a progress log entry."""
        self.progress_log.append(
            ProgressEntry(
                timestamp=datetime.now(timezone.utc),
                message=message,
            )
        )
        self.updated_at = datetime.now(timezone.utc)

    def add_task(self, description: str, **kwargs) -> PlanTask:
        """Add a task to the plan."""
        task = PlanTask(
            id=str(uuid.uuid4())[:8],
            description=description,
            **kwargs,
        )
        self.tasks.append(task)
        self.updated_at = datetime.now(timezone.utc)
        return task

    def add_question(
        self,
        question: str,
        question_type: str = "text",
        options: list[str] = None,
        required: bool = True,
    ) -> ClarificationQuestion:
        """Add a clarification question to the plan."""
        q = ClarificationQuestion(
            id=str(uuid.uuid4())[:8],
            question=question,
            question_type=question_type,
            options=options or [],
            required=required,
        )
        self.questions.append(q)
        self.updated_at = datetime.now(timezone.utc)
        return q

    def answer_question(self, question_id: str, answer: str) -> bool:
        """Record an answer to a clarification question."""
        for q in self.questions:
            if q.id == question_id:
                q.answer = answer
                q.answered_at = datetime.now(timezone.utc)
                self.updated_at = datetime.now(timezone.utc)
                return True
        return False

    def complete_task(self, task_id: str) -> bool:
        """Mark a task as completed (implementation done, not yet verified)."""
        for task in self.tasks:
            if task.id == task_id:
                task.completed = True
                self.updated_at = datetime.now(timezone.utc)
                return True
        return False

    def verify_task(self, task_id: str, verification_notes: str = "") -> bool:
        """Mark a task as verified (tests pass, changes validated).

        A task must be completed before it can be verified.
        """
        for task in self.tasks:
            if task.id == task_id:
                if not task.completed:
                    return False  # Must complete before verify
                task.verified = True
                task.verification_notes = verification_notes
                self.updated_at = datetime.now(timezone.utc)
                return True
        return False

    def get_unanswered_questions(self) -> list[ClarificationQuestion]:
        """Get all unanswered questions."""
        return [q for q in self.questions if q.answer is None]

    def get_incomplete_tasks(self) -> list[PlanTask]:
        """Get all incomplete tasks (not completed)."""
        return [t for t in self.tasks if not t.completed]

    def get_unverified_tasks(self) -> list[PlanTask]:
        """Get all unverified tasks (completed but not verified)."""
        return [t for t in self.tasks if t.completed and not t.verified]

    def get_completed_unverified_tasks(self) -> list[PlanTask]:
        """Get tasks that are completed but not yet verified."""
        return [t for t in self.tasks if t.completed and not t.verified]

    def all_tasks_verified(self) -> bool:
        """Check if all tasks are verified."""
        return all(t.verified for t in self.tasks) if self.tasks else True


class PlanManager:
    """Manages plan storage and lifecycle operations."""

    def __init__(self, base_dir: Path):
        """Initialize the plan manager.

        Args:
            base_dir: Base directory for persona (e.g., ~/.silica/personas/default)
        """
        self.base_dir = Path(base_dir)
        self.plans_dir = self.base_dir / "plans"
        self.active_dir = self.plans_dir / "active"
        self.completed_dir = self.plans_dir / "completed"

        # Ensure directories exist
        self.active_dir.mkdir(parents=True, exist_ok=True)
        self.completed_dir.mkdir(parents=True, exist_ok=True)

    def create_plan(
        self, title: str, session_id: str, context: str = "", root_dir: str = ""
    ) -> Plan:
        """Create a new plan.

        Args:
            title: Title/topic for the plan
            session_id: Current session ID
            context: Initial context description
            root_dir: Project root directory this plan belongs to

        Returns:
            The newly created Plan
        """
        now = datetime.now(timezone.utc)
        plan = Plan(
            id=str(uuid.uuid4())[:8],
            title=title,
            status=PlanStatus.DRAFT,
            session_id=session_id,
            created_at=now,
            updated_at=now,
            root_dir=root_dir,
            context=context,
        )
        plan.add_progress(f"Plan created: {title}")
        self._save_plan(plan)
        return plan

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        """Get a plan by ID.

        Args:
            plan_id: The plan ID to look up

        Returns:
            The Plan if found, None otherwise
        """
        # Check active first, then completed
        for directory in [self.active_dir, self.completed_dir]:
            plan_file = directory / f"{plan_id}.md"
            if plan_file.exists():
                try:
                    return Plan.from_markdown(plan_file.read_text())
                except Exception:
                    pass
        return None

    def update_plan(self, plan: Plan) -> None:
        """Update an existing plan.

        Args:
            plan: The plan to update
        """
        plan.updated_at = datetime.now(timezone.utc)
        self._save_plan(plan)

    def list_active_plans(self, root_dir: str | None = None) -> list[Plan]:
        """List all active (non-completed, non-abandoned) plans.

        Args:
            root_dir: If provided, only return plans for this project root.
                      If None, returns all active plans.

        Returns:
            List of active plans, sorted by last updated (newest first)
        """
        plans = []
        for plan_file in self.active_dir.glob("*.md"):
            try:
                plan = Plan.from_markdown(plan_file.read_text())

                # Filter by root_dir if specified
                if root_dir is not None:
                    import os

                    plan_root = os.path.normpath(plan.root_dir) if plan.root_dir else ""
                    filter_root = os.path.normpath(root_dir)
                    if plan_root != filter_root:
                        continue

                plans.append(plan)
            except Exception:
                pass
        return sorted(plans, key=lambda p: p.updated_at, reverse=True)

    def list_completed_plans(
        self, limit: int = 10, root_dir: str | None = None
    ) -> list[Plan]:
        """List completed/abandoned plans.

        Args:
            limit: Maximum number of plans to return
            root_dir: If provided, only return plans for this project root.

        Returns:
            List of completed plans, sorted by completion date (newest first)
        """
        plans = []
        for plan_file in self.completed_dir.glob("*.md"):
            try:
                plan = Plan.from_markdown(plan_file.read_text())

                # Filter by root_dir if specified
                if root_dir is not None:
                    import os

                    plan_root = os.path.normpath(plan.root_dir) if plan.root_dir else ""
                    filter_root = os.path.normpath(root_dir)
                    if plan_root != filter_root:
                        continue

                plans.append(plan)
            except Exception:
                pass
        plans = sorted(plans, key=lambda p: p.updated_at, reverse=True)
        return plans[:limit]

    def submit_for_review(self, plan_id: str) -> bool:
        """Submit a plan for user review.

        Args:
            plan_id: ID of the plan to submit

        Returns:
            True if successful, False otherwise
        """
        plan = self.get_plan(plan_id)
        if plan and plan.status == PlanStatus.DRAFT:
            plan.status = PlanStatus.IN_REVIEW
            plan.add_progress("Plan submitted for review")
            self.update_plan(plan)
            return True
        return False

    def approve_plan(self, plan_id: str) -> bool:
        """Approve a plan for execution.

        Args:
            plan_id: ID of the plan to approve

        Returns:
            True if successful, False otherwise
        """
        plan = self.get_plan(plan_id)
        if plan and plan.status == PlanStatus.IN_REVIEW:
            plan.status = PlanStatus.APPROVED
            plan.add_progress("Plan approved for execution")
            self.update_plan(plan)
            return True
        return False

    def start_execution(self, plan_id: str) -> bool:
        """Mark a plan as in-progress.

        Args:
            plan_id: ID of the plan to start

        Returns:
            True if successful, False otherwise
        """
        plan = self.get_plan(plan_id)
        if plan and plan.status == PlanStatus.APPROVED:
            plan.status = PlanStatus.IN_PROGRESS
            plan.add_progress("Plan execution started")
            self.update_plan(plan)
            return True
        return False

    def complete_plan(self, plan_id: str, notes: str = "") -> bool:
        """Mark a plan as completed and archive it.

        Args:
            plan_id: ID of the plan to complete
            notes: Optional completion notes

        Returns:
            True if successful, False otherwise
        """
        plan = self.get_plan(plan_id)
        if plan and plan.status in [PlanStatus.IN_PROGRESS, PlanStatus.APPROVED]:
            plan.status = PlanStatus.COMPLETED
            plan.completion_notes = notes
            plan.add_progress("Plan completed")

            # Move from active to completed
            self._archive_plan(plan)
            return True
        return False

    def abandon_plan(self, plan_id: str, reason: str = "") -> bool:
        """Abandon a plan and archive it.

        Args:
            plan_id: ID of the plan to abandon
            reason: Optional reason for abandonment

        Returns:
            True if successful, False otherwise
        """
        plan = self.get_plan(plan_id)
        if plan and plan.status not in [PlanStatus.COMPLETED, PlanStatus.ABANDONED]:
            plan.status = PlanStatus.ABANDONED
            if reason:
                plan.add_progress(f"Plan abandoned: {reason}")
            else:
                plan.add_progress("Plan abandoned")

            # Move from active to completed
            self._archive_plan(plan)
            return True
        return False

    def _save_plan(self, plan: Plan) -> None:
        """Save a plan to the appropriate directory.

        Args:
            plan: The plan to save
        """
        if plan.status in [PlanStatus.COMPLETED, PlanStatus.ABANDONED]:
            directory = self.completed_dir
        else:
            directory = self.active_dir

        plan_file = directory / f"{plan.id}.md"
        plan_file.write_text(plan.to_markdown())

    def _archive_plan(self, plan: Plan) -> None:
        """Move a plan from active to completed directory.

        Args:
            plan: The plan to archive
        """
        # Remove from active directory if exists
        active_file = self.active_dir / f"{plan.id}.md"
        if active_file.exists():
            active_file.unlink()

        # Save to completed directory
        completed_file = self.completed_dir / f"{plan.id}.md"
        completed_file.write_text(plan.to_markdown())
