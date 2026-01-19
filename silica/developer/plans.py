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
from typing import Literal, Optional
import json
import os
import re
import subprocess
import unicodedata
import uuid


def slugify(text: str, max_length: int = 50) -> str:
    """Convert text to a URL/branch-friendly slug.

    Examples:
        "Add User Avatars" -> "add-user-avatars"
        "Fix pagination bug #123" -> "fix-pagination-bug-123"
        "Refactor auth/middleware" -> "refactor-auth-middleware"
    """
    # Normalize unicode characters
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    # Convert to lowercase
    text = text.lower()
    # Replace any non-alphanumeric with hyphens
    text = re.sub(r"[^a-z0-9]+", "-", text)
    # Remove leading/trailing hyphens
    text = text.strip("-")
    # Collapse multiple hyphens
    text = re.sub(r"-+", "-", text)
    # Truncate to max_length, but don't cut mid-word
    if len(text) > max_length:
        text = text[:max_length].rsplit("-", 1)[0]
    return text or "plan"


# Storage location constants
LOCATION_LOCAL = "local"
LOCATION_GLOBAL = "global"


def get_git_root(cwd: Path | str | None = None) -> Path | None:
    """Find git repo root, or None if not in a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd or Path.cwd(),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass
    return None


def get_local_plans_dir(project_root: Path) -> Path:
    """Get the local plans directory for a project.

    Preference order:
    - .silica/plans if .silica exists
    - .agent/plans if .agent exists
    - .agent/plans for new (neither exists)

    We prefer .agent for new plans because .silica is typically gitignored
    (contains remote workspace info), while .agent can be committed if desired.
    """
    silica_dir = project_root / ".silica"
    agent_dir = project_root / ".agent"
    silica_plans = silica_dir / "plans"
    agent_plans = agent_dir / "plans"

    # If .silica/plans exists, use it
    if silica_plans.exists():
        return silica_plans
    # If .agent/plans exists, use it
    if agent_plans.exists():
        return agent_plans
    # If .silica exists (but not plans), use .silica/plans
    if silica_dir.exists():
        return silica_plans
    # If .agent exists (but not plans), use .agent/plans
    if agent_dir.exists():
        return agent_plans
    # Neither exists - prefer .agent for new plans (see docstring)
    return agent_plans


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

    Tasks can have dependencies (other task IDs that must complete first)
    and can be subtasks of a parent task (via parent_task_id).
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
    # Subtask support: if set, this task is a child of the specified parent task
    parent_task_id: Optional[str] = None
    # Dependency satisfaction level: if True, deps must be verified (not just completed)
    require_verified_deps: bool = False

    def to_dict(self) -> dict:
        result = {
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
        # Only include optional fields if they have non-default values
        if self.parent_task_id:
            result["parent_task_id"] = self.parent_task_id
        if self.require_verified_deps:
            result["require_verified_deps"] = self.require_verified_deps
        return result

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
            parent_task_id=data.get("parent_task_id"),
            require_verified_deps=data.get("require_verified_deps", False),
        )


@dataclass
class Milestone:
    """A milestone groups related tasks within a plan.

    Milestones provide checkpoints for complex plans, encouraging completion
    of related tasks before moving on. Tasks not assigned to any milestone
    are in an implicit "Uncategorized" group.
    """

    id: str
    title: str
    description: str = ""
    task_ids: list[str] = field(default_factory=list)  # Task IDs in this milestone
    completed: bool = False
    order: int = 0  # Display/execution order (lower = earlier)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "task_ids": self.task_ids,
            "completed": self.completed,
            "order": self.order,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Milestone":
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            title=data.get("title", "Untitled Milestone"),
            description=data.get("description", ""),
            task_ids=data.get("task_ids", []),
            completed=data.get("completed", False),
            order=data.get("order", 0),
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


def get_agent_version() -> str:
    """Get agent version as tag or short SHA.

    Returns the git tag if HEAD is tagged, otherwise the short SHA.
    Falls back to 'unknown' if git is not available.
    """
    try:
        # Try to get tag at HEAD
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()

        # Fall back to short SHA
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def get_silica_version() -> str:
    """Get the silica package version."""
    try:
        from silica import __version__

        return __version__
    except ImportError:
        return "unknown"


@dataclass
class MetricDefinition:
    """Definition of a trackable metric for a plan.

    Metrics can be either burn-up (higher is better) or burn-down (lower is better).
    The capture_command is a shell command that outputs the metric value.
    """

    name: str  # e.g., "tests_passing", "test_failures"
    metric_type: str = "int"  # "int", "float", "percent"
    direction: str = "up"  # "up" (higher is better) or "down" (lower is better)
    capture_command: str = ""  # Shell command to capture value
    description: str = ""  # Human-readable description
    target_value: float | None = None  # Optional goal value (0 for burn-down)
    validated: bool = False  # Has the capture command been tested?

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "metric_type": self.metric_type,
            "direction": self.direction,
            "capture_command": self.capture_command,
            "description": self.description,
            "target_value": self.target_value,
            "validated": self.validated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MetricDefinition":
        return cls(
            name=data.get("name", ""),
            metric_type=data.get("metric_type", "int"),
            direction=data.get("direction", "up"),
            capture_command=data.get("capture_command", ""),
            description=data.get("description", ""),
            target_value=data.get("target_value"),
            validated=data.get("validated", False),
        )


@dataclass
class MetricSnapshot:
    """A point-in-time capture of all metrics.

    Snapshots are taken at plan milestones (start, task completion, end)
    and can be manually triggered. They track both custom metrics and
    cost/token usage.
    """

    timestamp: datetime
    wall_clock_seconds: float  # Seconds since plan execution started
    trigger: str  # "plan_start", "task_complete:abc123", "manual", "plan_end"

    # Cost metrics (cumulative since plan start)
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cached_tokens: int = 0
    cost_dollars: float = 0.0

    # Version info
    agent_version: str = ""
    silica_version: str = ""

    # Custom metrics
    metrics: dict[str, float] = field(default_factory=dict)
    metric_errors: dict[str, str] = field(default_factory=dict)  # capture failures

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "wall_clock_seconds": self.wall_clock_seconds,
            "trigger": self.trigger,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
            "cached_tokens": self.cached_tokens,
            "cost_dollars": self.cost_dollars,
            "agent_version": self.agent_version,
            "silica_version": self.silica_version,
            "metrics": self.metrics,
            "metric_errors": self.metric_errors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MetricSnapshot":
        timestamp = datetime.now(timezone.utc)
        if data.get("timestamp"):
            try:
                timestamp = datetime.fromisoformat(
                    data["timestamp"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        return cls(
            timestamp=timestamp,
            wall_clock_seconds=data.get("wall_clock_seconds", 0.0),
            trigger=data.get("trigger", ""),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            thinking_tokens=data.get("thinking_tokens", 0),
            cached_tokens=data.get("cached_tokens", 0),
            cost_dollars=data.get("cost_dollars", 0.0),
            agent_version=data.get("agent_version", ""),
            silica_version=data.get("silica_version", ""),
            metrics=data.get("metrics", {}),
            metric_errors=data.get("metric_errors", {}),
        )


@dataclass
class PlanMetrics:
    """Metrics tracking for a plan.

    Contains metric definitions, snapshots over time, and baseline
    cost information for calculating deltas.
    """

    definitions: list[MetricDefinition] = field(default_factory=list)
    snapshots: list[MetricSnapshot] = field(default_factory=list)
    execution_started_at: datetime | None = None
    # Baseline tokens at plan start for calculating deltas
    baseline_input_tokens: int = 0
    baseline_output_tokens: int = 0
    baseline_thinking_tokens: int = 0
    baseline_cached_tokens: int = 0
    baseline_cost_dollars: float = 0.0

    def to_dict(self) -> dict:
        return {
            "definitions": [d.to_dict() for d in self.definitions],
            "snapshots": [s.to_dict() for s in self.snapshots],
            "execution_started_at": self.execution_started_at.isoformat()
            if self.execution_started_at
            else None,
            "baseline_input_tokens": self.baseline_input_tokens,
            "baseline_output_tokens": self.baseline_output_tokens,
            "baseline_thinking_tokens": self.baseline_thinking_tokens,
            "baseline_cached_tokens": self.baseline_cached_tokens,
            "baseline_cost_dollars": self.baseline_cost_dollars,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanMetrics":
        execution_started_at = None
        if data.get("execution_started_at"):
            try:
                execution_started_at = datetime.fromisoformat(
                    data["execution_started_at"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        return cls(
            definitions=[
                MetricDefinition.from_dict(d) for d in data.get("definitions", [])
            ],
            snapshots=[MetricSnapshot.from_dict(s) for s in data.get("snapshots", [])],
            execution_started_at=execution_started_at,
            baseline_input_tokens=data.get("baseline_input_tokens", 0),
            baseline_output_tokens=data.get("baseline_output_tokens", 0),
            baseline_thinking_tokens=data.get("baseline_thinking_tokens", 0),
            baseline_cached_tokens=data.get("baseline_cached_tokens", 0),
            baseline_cost_dollars=data.get("baseline_cost_dollars", 0.0),
        )

    def get_start_snapshot(self) -> MetricSnapshot | None:
        """Get the plan_start snapshot if it exists."""
        for snapshot in self.snapshots:
            if snapshot.trigger == "plan_start":
                return snapshot
        return None

    def get_previous_snapshot(self) -> MetricSnapshot | None:
        """Get the most recent snapshot."""
        if self.snapshots:
            return self.snapshots[-1]
        return None


@dataclass
class Plan:
    """A structured plan for complex changes."""

    id: str
    title: str
    status: PlanStatus
    session_id: str
    created_at: datetime
    updated_at: datetime
    root_dirs: list[str] = field(default_factory=list)  # Project directories
    storage_location: str = LOCATION_LOCAL  # "local" or "global"
    pull_request: str = ""  # Associated PR URL or number (e.g., "#123" or full URL)
    # Shelving and remote execution
    shelved: bool = False  # Approved but deferred for later/remote execution
    remote_workspace: str = ""  # Remote workspace name if pushed
    remote_branch: str = ""  # Branch name for remote execution
    remote_started_at: datetime | None = None  # When plan was pushed to remote
    context: str = ""
    approach: str = ""
    tasks: list[PlanTask] = field(default_factory=list)
    milestones: list[Milestone] = field(
        default_factory=list
    )  # Optional milestone groupings
    questions: list[ClarificationQuestion] = field(default_factory=list)
    considerations: dict[str, str] = field(default_factory=dict)
    progress_log: list[ProgressEntry] = field(default_factory=list)
    completion_notes: str = ""
    # Metrics tracking
    metrics: PlanMetrics = field(default_factory=PlanMetrics)

    def get_slug(self) -> str:
        """Get a slugified version of the plan title."""
        return slugify(self.title)

    @property
    def root_dir(self) -> str:
        """Backward compatibility: return first root_dir or empty string."""
        return self.root_dirs[0] if self.root_dirs else ""

    def matches_directory(self, directory: str) -> bool:
        """Check if this plan is associated with the given directory."""
        if not directory or not self.root_dirs:
            return True  # No filter or no association = match
        norm_dir = os.path.normpath(directory)
        return any(os.path.normpath(d) == norm_dir for d in self.root_dirs)

    def to_dict(self) -> dict:
        """Convert plan to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "root_dirs": self.root_dirs,
            "storage_location": self.storage_location,
            "pull_request": self.pull_request,
            "shelved": self.shelved,
            "remote_workspace": self.remote_workspace,
            "remote_branch": self.remote_branch,
            "remote_started_at": self.remote_started_at.isoformat()
            if self.remote_started_at
            else None,
            "context": self.context,
            "approach": self.approach,
            "tasks": [t.to_dict() for t in self.tasks],
            "milestones": [m.to_dict() for m in self.milestones],
            "questions": [q.to_dict() for q in self.questions],
            "considerations": self.considerations,
            "progress_log": [p.to_dict() for p in self.progress_log],
            "completion_notes": self.completion_notes,
            "metrics": self.metrics.to_dict(),
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

        # Handle backward compatibility: root_dir -> root_dirs
        root_dirs = data.get("root_dirs", [])
        if not root_dirs and data.get("root_dir"):
            root_dirs = [data["root_dir"]]

        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            title=data.get("title", "Untitled Plan"),
            status=PlanStatus(data.get("status", "draft")),
            session_id=data.get("session_id", ""),
            created_at=created_at,
            updated_at=updated_at,
            root_dirs=root_dirs,
            storage_location=data.get("storage_location", LOCATION_LOCAL),
            pull_request=data.get("pull_request", ""),
            shelved=data.get("shelved", False),
            remote_workspace=data.get("remote_workspace", ""),
            remote_branch=data.get("remote_branch", ""),
            remote_started_at=datetime.fromisoformat(data["remote_started_at"])
            if data.get("remote_started_at")
            else None,
            context=data.get("context", ""),
            approach=data.get("approach", ""),
            tasks=[PlanTask.from_dict(t) for t in data.get("tasks", [])],
            milestones=[Milestone.from_dict(m) for m in data.get("milestones", [])],
            questions=[
                ClarificationQuestion.from_dict(q) for q in data.get("questions", [])
            ],
            considerations=data.get("considerations", {}),
            progress_log=[
                ProgressEntry.from_dict(p) for p in data.get("progress_log", [])
            ],
            completion_notes=data.get("completion_notes", ""),
            metrics=PlanMetrics.from_dict(data.get("metrics", {})),
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
        if self.shelved:
            lines.append("**Shelved:** Yes (awaiting remote execution)")
        if self.remote_workspace:
            lines.append(f"**Remote Workspace:** {self.remote_workspace}")
        if self.remote_branch:
            lines.append(f"**Branch:** {self.remote_branch}")
        if self.pull_request:
            lines.append(f"**Pull Request:** {self.pull_request}")
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
            # Helper to render a single task
            def render_task(task: PlanTask, indent: str = "") -> list[str]:
                task_lines = []
                # Show status: ⬜ pending, ✅ completed, ✓✓ verified
                if task.verified:
                    status = "✓✓"
                elif task.completed:
                    status = "✅"
                else:
                    status = "⬜"

                # Add readiness indicator for incomplete tasks
                readiness = ""
                if not task.completed and not task.parent_task_id:
                    if self.is_task_ready(task.id):
                        readiness = " [READY]"
                    elif task.dependencies:
                        blocking = self.get_blocking_tasks(task.id)
                        if blocking:
                            blocking_ids = ", ".join(t.id for t in blocking[:3])
                            if len(blocking) > 3:
                                blocking_ids += f" +{len(blocking)-3} more"
                            readiness = f" [BLOCKED by {blocking_ids}]"

                task_lines.append(
                    f"{indent}- {status} **{task.description}** (id: {task.id}){readiness}"
                )
                if task.details:
                    task_lines.append(f"{indent}  - Details: {task.details}")
                if task.files:
                    task_lines.append(f"{indent}  - Files: {', '.join(task.files)}")
                if task.tests:
                    task_lines.append(f"{indent}  - Tests: {task.tests}")
                if task.dependencies:
                    task_lines.append(
                        f"{indent}  - Dependencies: {', '.join(task.dependencies)}"
                    )
                if task.verification_notes:
                    task_lines.append(
                        f"{indent}  - Verification: {task.verification_notes}"
                    )

                # Render subtasks
                subtasks = self.get_subtasks(task.id)
                if subtasks:
                    for subtask in subtasks:
                        task_lines.extend(render_task(subtask, indent + "  "))

                task_lines.append("")
                return task_lines

            # Group tasks by milestone
            if self.milestones:
                # Track which tasks are assigned to milestones
                assigned_task_ids: set[str] = set()
                for milestone in sorted(self.milestones, key=lambda m: m.order):
                    assigned_task_ids.update(milestone.task_ids)

                # Render each milestone
                for milestone in sorted(self.milestones, key=lambda m: m.order):
                    milestone_tasks = [
                        t
                        for t in self.tasks
                        if t.id in milestone.task_ids and not t.parent_task_id
                    ]
                    completed = sum(1 for t in milestone_tasks if t.completed)
                    verified = sum(1 for t in milestone_tasks if t.verified)
                    total = len(milestone_tasks)

                    # Milestone status
                    if milestone.completed or (total > 0 and verified == total):
                        m_status = "✓"
                    elif total > 0 and completed == total:
                        m_status = "⏳"  # All completed, awaiting verification
                    else:
                        m_status = ""

                    lines.append(
                        f"### {m_status} {milestone.title} ({verified}✓/{total})"
                    )
                    if milestone.description:
                        lines.append(f"_{milestone.description}_")
                    lines.append("")

                    for task in milestone_tasks:
                        lines.extend(render_task(task))

                # Render uncategorized tasks
                uncategorized = [
                    t
                    for t in self.tasks
                    if t.id not in assigned_task_ids and not t.parent_task_id
                ]
                if uncategorized:
                    lines.append("### Uncategorized Tasks")
                    lines.append("")
                    for task in uncategorized:
                        lines.extend(render_task(task))
            else:
                # No milestones - render all top-level tasks
                for task in self.tasks:
                    if not task.parent_task_id:
                        lines.extend(render_task(task))
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

        # Metrics
        if self.metrics.definitions:
            lines.append("## Metrics")
            lines.append("")

            # Show metric definitions
            lines.append("### Tracked Metrics")
            lines.append("")
            for d in self.metrics.definitions:
                dir_indicator = "↑" if d.direction == "up" else "↓"
                validated = "✓" if d.validated else "⚠️ not configured"
                target = (
                    f", target: {d.target_value}" if d.target_value is not None else ""
                )
                lines.append(
                    f"- **{d.name}** {dir_indicator} ({d.metric_type}{target}) {validated}"
                )
            lines.append("")

            # Show latest snapshot if available
            if self.metrics.snapshots:
                latest = self.metrics.snapshots[-1]
                start = self.metrics.get_start_snapshot()

                lines.append("### Latest Snapshot")
                lines.append("")
                lines.append(f"**Trigger:** {latest.trigger}")
                lines.append(
                    f"**Time:** {latest.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                )

                mins = int(latest.wall_clock_seconds // 60)
                secs = int(latest.wall_clock_seconds % 60)
                lines.append(f"**Elapsed:** {mins}m {secs}s")

                cost_str = (
                    f"${latest.cost_dollars:.4f}"
                    if latest.cost_dollars < 1
                    else f"${latest.cost_dollars:.2f}"
                )
                lines.append(
                    f"**Cost:** {cost_str} ({latest.input_tokens:,} in, {latest.output_tokens:,} out)"
                )
                lines.append("")

                # Show metric values
                if latest.metrics:
                    lines.append("| Metric | Current | Δ Start | Target | Progress |")
                    lines.append("|--------|---------|---------|--------|----------|")

                    for d in self.metrics.definitions:
                        if d.name in latest.metrics:
                            current = latest.metrics[d.name]
                            current_str = (
                                f"{current:.1f}"
                                if isinstance(current, float)
                                and not current.is_integer()
                                else str(int(current))
                            )

                            # Delta from start
                            delta_start = "-"
                            if start and d.name in start.metrics:
                                diff = current - start.metrics[d.name]
                                if diff != 0:
                                    sign = "+" if diff > 0 else ""
                                    delta_start = (
                                        f"{sign}{diff:.1f}"
                                        if isinstance(diff, float)
                                        else f"{sign}{int(diff)}"
                                    )

                            # Target and progress
                            target_str = (
                                str(int(d.target_value))
                                if d.target_value is not None
                                else "-"
                            )
                            progress = "-"
                            if d.target_value is not None:
                                if d.direction == "up" and d.target_value != 0:
                                    pct = (current / d.target_value) * 100
                                    progress = f"{pct:.1f}%"
                                elif (
                                    d.direction == "down"
                                    and start
                                    and d.name in start.metrics
                                ):
                                    start_val = start.metrics[d.name]
                                    if start_val != 0:
                                        pct = ((start_val - current) / start_val) * 100
                                        progress = f"{pct:.1f}%"

                            dir_indicator = "↑" if d.direction == "up" else "↓"
                            lines.append(
                                f"| {d.name} {dir_indicator} | {current_str} | {delta_start} | {target_str} | {progress} |"
                            )

                    lines.append("")

                # Show errors if any
                if latest.metric_errors:
                    lines.append("**Metric Errors:**")
                    for name, error in latest.metric_errors.items():
                        lines.append(f"- {name}: {error}")
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

    def get_task_by_id(self, task_id: str) -> Optional[PlanTask]:
        """Get a task by its ID."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    # Subtask helper methods

    def get_subtasks(self, task_id: str) -> list[PlanTask]:
        """Get all subtasks of a given task.

        Args:
            task_id: The parent task ID

        Returns:
            List of subtasks (tasks with parent_task_id == task_id)
        """
        return [t for t in self.tasks if t.parent_task_id == task_id]

    def get_parent_task(self, task_id: str) -> Optional[PlanTask]:
        """Get the parent task of a subtask.

        Args:
            task_id: The subtask ID

        Returns:
            The parent task, or None if this is a top-level task
        """
        task = self.get_task_by_id(task_id)
        if task is None or task.parent_task_id is None:
            return None
        return self.get_task_by_id(task.parent_task_id)

    def is_container_task(self, task_id: str) -> bool:
        """Check if a task is a container (has subtasks).

        Args:
            task_id: The task ID to check

        Returns:
            True if the task has subtasks, False otherwise
        """
        return len(self.get_subtasks(task_id)) > 0

    def is_subtask(self, task_id: str) -> bool:
        """Check if a task is a subtask (has a parent).

        Args:
            task_id: The task ID to check

        Returns:
            True if the task has a parent, False otherwise
        """
        task = self.get_task_by_id(task_id)
        return task is not None and task.parent_task_id is not None

    def get_top_level_tasks(self) -> list[PlanTask]:
        """Get all top-level tasks (not subtasks).

        Returns:
            List of tasks that don't have a parent
        """
        return [t for t in self.tasks if t.parent_task_id is None]

    def are_all_subtasks_complete(self, task_id: str) -> bool:
        """Check if all subtasks of a task are complete.

        Args:
            task_id: The parent task ID

        Returns:
            True if all subtasks are completed, False otherwise.
            Returns True if the task has no subtasks.
        """
        subtasks = self.get_subtasks(task_id)
        if not subtasks:
            return True
        return all(t.completed for t in subtasks)

    def are_all_subtasks_verified(self, task_id: str) -> bool:
        """Check if all subtasks of a task are verified.

        Args:
            task_id: The parent task ID

        Returns:
            True if all subtasks are verified, False otherwise.
            Returns True if the task has no subtasks.
        """
        subtasks = self.get_subtasks(task_id)
        if not subtasks:
            return True
        return all(t.verified for t in subtasks)

    def is_dependency_satisfied(
        self, dep_task_id: str, require_verified: bool = False
    ) -> bool:
        """Check if a dependency task is satisfied.

        Args:
            dep_task_id: The task ID of the dependency
            require_verified: If True, dependency must be verified; if False, just completed

        Returns:
            True if the dependency is satisfied, False otherwise
        """
        dep_task = self.get_task_by_id(dep_task_id)
        if dep_task is None:
            # Dependency task doesn't exist - treat as satisfied (may have been removed)
            return True
        if require_verified:
            return dep_task.verified
        return dep_task.completed

    # Circular dependency detection

    def _detect_cycle_from(
        self, task_id: str, visited: set[str], rec_stack: set[str]
    ) -> list[str] | None:
        """DFS helper to detect cycles starting from a task.

        Args:
            task_id: Current task being visited
            visited: Set of all visited tasks
            rec_stack: Set of tasks in current recursion stack

        Returns:
            List of task IDs forming a cycle, or None if no cycle found
        """
        visited.add(task_id)
        rec_stack.add(task_id)

        task = self.get_task_by_id(task_id)
        if task:
            for dep_id in task.dependencies:
                if dep_id not in visited:
                    cycle = self._detect_cycle_from(dep_id, visited, rec_stack)
                    if cycle is not None:
                        return cycle
                elif dep_id in rec_stack:
                    # Found a cycle - build the cycle path
                    return [dep_id, task_id]

        rec_stack.remove(task_id)
        return None

    def find_dependency_cycle(self) -> list[str] | None:
        """Find a dependency cycle if one exists.

        Uses DFS to detect cycles in the dependency graph.

        Returns:
            List of task IDs forming a cycle (in order), or None if no cycle exists.
            The first and last elements may be the same to show the cycle point.
        """
        visited: set[str] = set()
        rec_stack: set[str] = set()

        for task in self.tasks:
            if task.id not in visited:
                cycle = self._detect_cycle_from(task.id, visited, rec_stack)
                if cycle is not None:
                    return cycle

        return None

    def has_dependency_cycle(self) -> bool:
        """Check if there's a circular dependency in the plan.

        Returns:
            True if a cycle exists, False otherwise
        """
        return self.find_dependency_cycle() is not None

    def validate_dependencies(self) -> list[str]:
        """Validate all dependencies in the plan.

        Checks for:
        - Circular dependencies
        - References to non-existent tasks
        - Self-dependencies

        Returns:
            List of error messages. Empty list if all dependencies are valid.
        """
        errors = []

        # Check for circular dependencies
        cycle = self.find_dependency_cycle()
        if cycle:
            cycle_str = " -> ".join(cycle)
            errors.append(f"Circular dependency detected: {cycle_str}")

        # Check each task's dependencies
        task_ids = {t.id for t in self.tasks}
        for task in self.tasks:
            for dep_id in task.dependencies:
                # Check for self-dependency
                if dep_id == task.id:
                    errors.append(f"Task '{task.id}' has self-dependency")
                # Check for non-existent dependency
                elif dep_id not in task_ids:
                    errors.append(
                        f"Task '{task.id}' depends on non-existent task '{dep_id}'"
                    )

        return errors

    def would_create_cycle(self, task_id: str, new_dep_id: str) -> bool:
        """Check if adding a dependency would create a cycle.

        Args:
            task_id: The task that would get the new dependency
            new_dep_id: The task ID that would become a dependency

        Returns:
            True if adding this dependency would create a cycle
        """
        if task_id == new_dep_id:
            return True  # Self-dependency is a cycle

        # Check if new_dep_id already depends (transitively) on task_id
        # If so, adding task_id -> new_dep_id would create a cycle
        visited: set[str] = set()
        to_visit = [new_dep_id]

        while to_visit:
            current = to_visit.pop()
            if current == task_id:
                return True  # Found path from new_dep back to task
            if current in visited:
                continue
            visited.add(current)

            current_task = self.get_task_by_id(current)
            if current_task:
                to_visit.extend(current_task.dependencies)

        return False

    def is_task_ready(self, task_id: str) -> bool:
        """Check if a task is ready to be worked on.

        A task is ready if:
        - It's not already completed
        - All its dependencies are satisfied (completed or verified based on task setting)

        Args:
            task_id: The task ID to check

        Returns:
            True if the task is ready, False otherwise
        """
        task = self.get_task_by_id(task_id)
        if task is None:
            return False
        if task.completed:
            return False  # Already done

        # Check all dependencies
        for dep_id in task.dependencies:
            if not self.is_dependency_satisfied(dep_id, task.require_verified_deps):
                return False
        return True

    def get_blocking_tasks(self, task_id: str) -> list[PlanTask]:
        """Get tasks that are blocking the given task.

        Returns the list of dependency tasks that are not yet satisfied.

        Args:
            task_id: The task ID to check

        Returns:
            List of tasks that are blocking this task
        """
        task = self.get_task_by_id(task_id)
        if task is None:
            return []

        blocking = []
        for dep_id in task.dependencies:
            if not self.is_dependency_satisfied(dep_id, task.require_verified_deps):
                dep_task = self.get_task_by_id(dep_id)
                if dep_task:
                    blocking.append(dep_task)
        return blocking

    def get_ready_tasks(self) -> list[PlanTask]:
        """Get all tasks that are ready to be worked on.

        Returns tasks that are:
        - Not completed
        - Have all dependencies satisfied
        - Are not subtasks (top-level only, subtasks accessed via parent)

        Returns:
            List of ready tasks in order
        """
        ready = []
        for task in self.tasks:
            if task.parent_task_id:
                continue  # Skip subtasks, they're accessed via parent
            if self.is_task_ready(task.id):
                ready.append(task)
        return ready

    def get_blocked_tasks(self) -> list[PlanTask]:
        """Get all tasks that are blocked by dependencies.

        Returns tasks that are:
        - Not completed
        - Have at least one unsatisfied dependency
        - Are not subtasks

        Returns:
            List of blocked tasks with their blocking dependencies
        """
        blocked = []
        for task in self.tasks:
            if task.parent_task_id:
                continue  # Skip subtasks
            if task.completed:
                continue  # Already done
            if task.dependencies and not self.is_task_ready(task.id):
                blocked.append(task)
        return blocked

    def can_run_parallel(self, task_id_a: str, task_id_b: str) -> bool:
        """Check if two tasks can run in parallel.

        Two tasks can run in parallel if:
        - Neither depends on the other (directly or transitively)
        - They don't share any files (no file overlap)

        Args:
            task_id_a: First task ID
            task_id_b: Second task ID

        Returns:
            True if tasks can run in parallel, False otherwise
        """
        task_a = self.get_task_by_id(task_id_a)
        task_b = self.get_task_by_id(task_id_b)

        if task_a is None or task_b is None:
            return False

        # Check for direct dependencies
        if task_id_b in task_a.dependencies or task_id_a in task_b.dependencies:
            return False

        # Check for file overlap
        files_a = set(task_a.files)
        files_b = set(task_b.files)
        if files_a & files_b:  # Intersection is non-empty
            return False

        return True

    def get_parallel_ready_tasks(self) -> list[list[PlanTask]]:
        """Get groups of tasks that can run in parallel.

        Returns ready tasks grouped by parallelizability. Tasks within each
        group can run concurrently with each other. The first group contains
        the maximum set of parallelizable tasks.

        This uses a greedy algorithm:
        1. Start with all ready tasks
        2. Build groups where no two tasks in a group share files
        3. Return all groups (some tasks may appear in multiple potential groupings)

        Returns:
            List of task groups. Each group is a list of tasks that can run together.
            Returns [[task]] for each task if no parallelism is possible.
        """
        ready = self.get_ready_tasks()
        if len(ready) <= 1:
            return [[t] for t in ready]

        # Build a parallelizable group greedily
        # Start with the first task, add others that don't conflict
        parallel_group = []
        remaining = list(ready)

        while remaining:
            # Start a new group with the first remaining task
            current_group = [remaining.pop(0)]
            still_remaining = []

            for task in remaining:
                # Check if this task can run with all tasks in current group
                can_add = True
                for group_task in current_group:
                    if not self.can_run_parallel(task.id, group_task.id):
                        can_add = False
                        break
                if can_add:
                    current_group.append(task)
                else:
                    still_remaining.append(task)

            parallel_group.append(current_group)
            remaining = still_remaining

        return parallel_group

    def get_max_parallel_tasks(self) -> list[PlanTask]:
        """Get the largest group of tasks that can all run in parallel.

        Convenience method that returns the first (largest) parallel group.

        Returns:
            List of tasks that can run concurrently
        """
        groups = self.get_parallel_ready_tasks()
        if groups:
            # Return the largest group
            return max(groups, key=len)
        return []

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
    """Manages plan storage and lifecycle operations.

    Supports two storage locations:
    - Local: Project directory (.agent/plans or .silica/plans)
    - Global: Persona directory (~/.silica/personas/{persona}/plans)

    Default behavior:
    - In git repo: store locally
    - Not in git repo: store globally
    - Explicit --local/--global flags override
    """

    def __init__(
        self,
        base_dir: Path,
        project_root: Path | None = None,
        default_location: Literal["auto", "local", "global"] = "auto",
    ):
        """Initialize the plan manager.

        Args:
            base_dir: Base directory for persona (e.g., ~/.silica/personas/default)
            project_root: Git repo root (None if not in a repo)
            default_location: Where to store new plans by default
        """
        self.base_dir = Path(base_dir)
        self.project_root = project_root
        self.default_location = default_location

        # Global storage (persona dir)
        self.global_plans_dir = self.base_dir / "plans"
        self.global_active_dir = self.global_plans_dir / "active"
        self.global_completed_dir = self.global_plans_dir / "completed"
        self.global_active_dir.mkdir(parents=True, exist_ok=True)
        self.global_completed_dir.mkdir(parents=True, exist_ok=True)

        # Local storage (project dir) - only if in a git repo
        self.local_plans_dir: Path | None = None
        self.local_active_dir: Path | None = None
        self.local_completed_dir: Path | None = None
        if project_root:
            self.local_plans_dir = get_local_plans_dir(project_root)
            self.local_active_dir = self.local_plans_dir / "active"
            self.local_completed_dir = self.local_plans_dir / "completed"

    # Backward compatibility properties
    @property
    def plans_dir(self) -> Path:
        return self.global_plans_dir

    @property
    def active_dir(self) -> Path:
        return self.global_active_dir

    @property
    def completed_dir(self) -> Path:
        return self.global_completed_dir

    def _get_storage_location(
        self, force_location: Literal["local", "global"] | None = None
    ) -> str:
        """Determine storage location for a new plan."""
        if force_location:
            return force_location
        if self.default_location == "local" and self.project_root:
            return LOCATION_LOCAL
        if self.default_location == "global":
            return LOCATION_GLOBAL
        # Auto: local if in git repo, global otherwise
        return LOCATION_LOCAL if self.project_root else LOCATION_GLOBAL

    def _get_dirs_for_location(self, location: str) -> tuple[Path, Path]:
        """Get (active_dir, completed_dir) for a storage location."""
        if location == LOCATION_LOCAL and self.local_active_dir:
            self.local_active_dir.mkdir(parents=True, exist_ok=True)
            self.local_completed_dir.mkdir(parents=True, exist_ok=True)
            return self.local_active_dir, self.local_completed_dir
        return self.global_active_dir, self.global_completed_dir

    def _get_all_active_dirs(self) -> list[tuple[Path, str]]:
        """Get all active directories with their location type."""
        dirs = [(self.global_active_dir, LOCATION_GLOBAL)]
        if self.local_active_dir and self.local_active_dir.exists():
            dirs.insert(0, (self.local_active_dir, LOCATION_LOCAL))  # Local first
        return dirs

    def _get_all_completed_dirs(self) -> list[tuple[Path, str]]:
        """Get all completed directories with their location type."""
        dirs = [(self.global_completed_dir, LOCATION_GLOBAL)]
        if self.local_completed_dir and self.local_completed_dir.exists():
            dirs.insert(0, (self.local_completed_dir, LOCATION_LOCAL))
        return dirs

    def create_plan(
        self,
        title: str,
        session_id: str,
        context: str = "",
        root_dir: str = "",
        location: Literal["local", "global"] | None = None,
    ) -> Plan:
        """Create a new plan.

        Args:
            title: Title/topic for the plan
            session_id: Current session ID
            context: Initial context description
            root_dir: Project root directory this plan belongs to
            location: Force storage location ("local" or "global")

        Returns:
            The newly created Plan
        """
        storage_loc = self._get_storage_location(location)
        root_dirs = [root_dir] if root_dir else []

        now = datetime.now(timezone.utc)
        plan = Plan(
            id=str(uuid.uuid4())[:8],
            title=title,
            status=PlanStatus.DRAFT,
            session_id=session_id,
            created_at=now,
            updated_at=now,
            root_dirs=root_dirs,
            storage_location=storage_loc,
            context=context,
        )
        plan.add_progress(f"Plan created: {title}")
        self._save_plan(plan)
        return plan

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        """Get a plan by ID. Searches both local and global locations.

        Args:
            plan_id: The plan ID to look up

        Returns:
            The Plan if found, None otherwise
        """
        # Search all active directories, then all completed
        for directory, loc in self._get_all_active_dirs():
            plan_file = directory / f"{plan_id}.md"
            if plan_file.exists():
                try:
                    plan = Plan.from_markdown(plan_file.read_text())
                    plan.storage_location = loc  # Ensure location is set
                    return plan
                except Exception:
                    pass

        for directory, loc in self._get_all_completed_dirs():
            plan_file = directory / f"{plan_id}.md"
            if plan_file.exists():
                try:
                    plan = Plan.from_markdown(plan_file.read_text())
                    plan.storage_location = loc
                    return plan
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
        """List all active plans from both local and global locations.

        Args:
            root_dir: If provided, only return plans matching this directory.

        Returns:
            List of active plans, sorted by last updated (newest first)
        """
        plans = []
        seen_ids = set()

        for directory, loc in self._get_all_active_dirs():
            if not directory.exists():
                continue
            for plan_file in directory.glob("*.md"):
                try:
                    plan = Plan.from_markdown(plan_file.read_text())
                    if plan.id in seen_ids:
                        continue
                    seen_ids.add(plan.id)
                    plan.storage_location = loc

                    # Filter by root_dir if specified
                    if root_dir is not None and not plan.matches_directory(root_dir):
                        continue

                    plans.append(plan)
                except Exception:
                    pass
        return sorted(plans, key=lambda p: p.updated_at, reverse=True)

    def list_completed_plans(
        self, limit: int = 10, root_dir: str | None = None
    ) -> list[Plan]:
        """List completed/abandoned plans from both locations.

        Args:
            limit: Maximum number of plans to return
            root_dir: If provided, only return plans matching this directory.

        Returns:
            List of completed plans, sorted by completion date (newest first)
        """
        plans = []
        seen_ids = set()

        for directory, loc in self._get_all_completed_dirs():
            if not directory.exists():
                continue
            for plan_file in directory.glob("*.md"):
                try:
                    plan = Plan.from_markdown(plan_file.read_text())
                    if plan.id in seen_ids:
                        continue
                    seen_ids.add(plan.id)
                    plan.storage_location = loc

                    # Filter by root_dir if specified
                    if root_dir is not None and not plan.matches_directory(root_dir):
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

    def approve_plan(self, plan_id: str, shelve: bool = False) -> bool:
        """Approve a plan for execution.

        Args:
            plan_id: ID of the plan to approve
            shelve: If True, mark as shelved (deferred for remote execution)

        Returns:
            True if successful, False otherwise
        """
        plan = self.get_plan(plan_id)
        if plan and plan.status == PlanStatus.IN_REVIEW:
            plan.status = PlanStatus.APPROVED
            plan.shelved = shelve
            if shelve:
                plan.add_progress("Plan approved and shelved for remote execution")
            else:
                plan.add_progress("Plan approved for execution")
            self.update_plan(plan)
            return True
        return False

    def list_shelved_plans(self, root_dir: str | None = None) -> list[Plan]:
        """List all approved and shelved plans ready for remote execution.

        Args:
            root_dir: If provided, only return plans matching this directory.

        Returns:
            List of shelved plans
        """
        plans = self.list_active_plans(root_dir=root_dir)
        return [p for p in plans if p.status == PlanStatus.APPROVED and p.shelved]

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

    def reopen_plan(self, plan_id: str, reason: str = "") -> bool:
        """Reopen a completed or abandoned plan.

        Transitions the plan back to IN_PROGRESS status and moves it
        from the completed directory back to the active directory.
        Task completion/verification state is preserved - the user or
        agent can decide which tasks need to be redone.

        Args:
            plan_id: ID of the plan to reopen
            reason: Optional reason for reopening

        Returns:
            True if successful, False otherwise
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return False

        if plan.status not in [PlanStatus.COMPLETED, PlanStatus.ABANDONED]:
            return False  # Can only reopen completed or abandoned plans

        # Clear completion notes since we're reopening
        plan.completion_notes = ""

        # Transition to IN_PROGRESS
        plan.status = PlanStatus.IN_PROGRESS

        if reason:
            plan.add_progress(f"Plan reopened: {reason}")
        else:
            plan.add_progress("Plan reopened")

        # Remove from completed directory
        for directory, _ in self._get_all_completed_dirs():
            completed_file = directory / f"{plan.id}.md"
            if completed_file.exists():
                completed_file.unlink()

        # Save to active directory
        self._save_plan(plan)
        return True

    def _save_plan(self, plan: Plan) -> None:
        """Save a plan to the appropriate directory based on its storage_location."""
        active_dir, completed_dir = self._get_dirs_for_location(plan.storage_location)

        if plan.status in [PlanStatus.COMPLETED, PlanStatus.ABANDONED]:
            directory = completed_dir
        else:
            directory = active_dir

        plan_file = directory / f"{plan.id}.md"
        plan_file.write_text(plan.to_markdown())

    def _archive_plan(self, plan: Plan) -> None:
        """Move a plan from active to completed directory."""
        # Remove from all active directories
        for directory, _ in self._get_all_active_dirs():
            active_file = directory / f"{plan.id}.md"
            if active_file.exists():
                active_file.unlink()

        # Save to completed directory for this plan's location
        _, completed_dir = self._get_dirs_for_location(plan.storage_location)
        completed_file = completed_dir / f"{plan.id}.md"
        completed_file.write_text(plan.to_markdown())

    def move_plan(
        self, plan_id: str, target_location: Literal["local", "global"]
    ) -> bool:
        """Move a plan between local and global storage.

        Args:
            plan_id: ID of the plan to move
            target_location: Where to move the plan

        Returns:
            True if successful, False otherwise
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return False

        if target_location == LOCATION_LOCAL and not self.project_root:
            return False  # Can't move to local without a git repo

        old_location = plan.storage_location

        # Remove from old location
        for directory, _ in (
            self._get_all_active_dirs() + self._get_all_completed_dirs()
        ):
            old_file = directory / f"{plan.id}.md"
            if old_file.exists():
                old_file.unlink()

        # Save to new location
        plan.storage_location = target_location
        plan.add_progress(f"Plan moved from {old_location} to {target_location}")
        self._save_plan(plan)
        return True
