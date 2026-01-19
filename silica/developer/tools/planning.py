"""Planning tools for structured plan mode workflow.

These tools enable the agent to enter a structured planning mode for complex changes,
ask clarifying questions to the user, and manage plan documents.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from silica.developer.tools.framework import tool
from silica.developer.plans import (
    MetricSnapshot,
    Plan,
    PlanManager,
    PlanStatus,
)

if TYPE_CHECKING:
    from silica.developer.context import AgentContext


def get_active_plan_status(context: "AgentContext") -> dict | None:
    """Get the status of the active plan for this session.

    This is used to show plan mode indicators in the prompt.
    Uses context.active_plan_id if set, otherwise falls back to most recent
    plan for the current project.

    Args:
        context: The agent context

    Returns:
        Dict with plan info if there's an active plan, None otherwise:
        {
            "id": str,
            "title": str,
            "slug": str,  # URL-friendly version of title
            "status": str,  # "planning" or "executing"
            "incomplete_tasks": int,
            "unverified_tasks": int,
            "verified_tasks": int,
            "total_tasks": int,
        }
    """
    plan_manager = _get_plan_manager(context)

    # First check for session-specific active plan
    plan = None
    if context.active_plan_id:
        plan = plan_manager.get_plan(context.active_plan_id)

    # Fallback to most recent plan for this project (for backwards compatibility)
    if plan is None:
        root_dir = _get_root_dir(context)
        active_plans = plan_manager.list_active_plans(root_dir=root_dir)
        if active_plans:
            plan = active_plans[0]

    if plan is None:
        return None

    # Determine if we're planning or executing
    if plan.status in (PlanStatus.DRAFT, PlanStatus.IN_REVIEW):
        status = "planning"
    elif plan.status in (PlanStatus.APPROVED, PlanStatus.IN_PROGRESS):
        status = "executing"
    else:
        return None

    incomplete = len(plan.get_incomplete_tasks())
    unverified = len(plan.get_unverified_tasks())
    verified = len([t for t in plan.tasks if t.verified])
    total = len(plan.tasks)
    ready_tasks = plan.get_ready_tasks()
    blocked_tasks = plan.get_blocked_tasks()
    parallel_tasks = plan.get_max_parallel_tasks()

    # Get current milestone
    current_milestone = None
    if plan.milestones:
        for m in sorted(plan.milestones, key=lambda x: x.order):
            m_tasks = [t for t in plan.tasks if t.id in m.task_ids]
            if m_tasks and not all(t.verified for t in m_tasks):
                current_milestone = {"id": m.id, "title": m.title}
                break

    return {
        "id": plan.id,
        "title": plan.title,
        "slug": plan.get_slug(),
        "status": status,
        "current_milestone": current_milestone,
        "ready_tasks": len(ready_tasks),
        "blocked_tasks": len(blocked_tasks),
        "parallel_tasks": len(parallel_tasks),
        "incomplete_tasks": incomplete,
        "unverified_tasks": unverified,
        "verified_tasks": verified,
        "total_tasks": total,
    }


def get_active_plan_id(context: "AgentContext") -> str | None:
    """Get the ID of the active plan for this session.

    Uses context.active_plan_id if set, otherwise falls back to most recent
    plan for the current project.

    This is used for context-aware /plan commands.

    Args:
        context: The agent context

    Returns:
        Plan ID if there's an active plan, None otherwise
    """
    # First check for session-specific active plan
    if context.active_plan_id:
        # Verify it still exists and is active
        plan_manager = _get_plan_manager(context)
        plan = plan_manager.get_plan(context.active_plan_id)
        if plan and plan.status not in (PlanStatus.COMPLETED, PlanStatus.ABANDONED):
            return context.active_plan_id
        # Clear stale reference
        context.active_plan_id = None

    # Fallback to most recent plan for this project
    plan_manager = _get_plan_manager(context)
    root_dir = _get_root_dir(context)
    active_plans = plan_manager.list_active_plans(root_dir=root_dir)

    if not active_plans:
        return None

    return active_plans[0].id


def get_ephemeral_plan_state(context: "AgentContext") -> str | None:
    """Generate an ephemeral plan state block for injection into user messages.

    This is injected before cache markers in the last user message to provide
    the agent with current plan state without accumulating in conversation history.

    Only returns content for plans that are IN_PROGRESS (actively being executed)
    and belong to this session (via context.active_plan_id).

    Args:
        context: The agent context

    Returns:
        Plan state block as string, or None if no active execution
    """
    plan_manager = _get_plan_manager(context)

    # First check for session-specific active plan
    plan = None
    if context.active_plan_id:
        plan = plan_manager.get_plan(context.active_plan_id)
        # Only show ephemeral state for IN_PROGRESS plans
        if plan and plan.status != PlanStatus.IN_PROGRESS:
            plan = None

    # Fallback to most recent IN_PROGRESS plan for this project
    if plan is None:
        root_dir = _get_root_dir(context)
        active_plans = plan_manager.list_active_plans(root_dir=root_dir)
        in_progress = [p for p in active_plans if p.status == PlanStatus.IN_PROGRESS]
        if in_progress:
            plan = in_progress[0]

    if plan is None:
        return None

    # Calculate progress
    total = len(plan.tasks)
    completed = len([t for t in plan.tasks if t.completed])
    verified = len([t for t in plan.tasks if t.verified])

    incomplete_tasks = plan.get_incomplete_tasks()
    unverified_tasks = plan.get_unverified_tasks()
    ready_tasks = plan.get_ready_tasks()
    blocked_tasks = plan.get_blocked_tasks()
    parallel_tasks = plan.get_max_parallel_tasks()

    # Build the state block
    lines = [
        "<current_plan_state>",
        f"**Active Plan:** {plan.title} (`{plan.id}`)",
        f"**Progress:** {verified}✓/{total} verified, {completed}/{total} completed",
        "",
    ]

    # Show current milestone if any
    if plan.milestones:
        current_milestone = None
        for m in sorted(plan.milestones, key=lambda x: x.order):
            milestone_tasks = [t for t in plan.tasks if t.id in m.task_ids]
            if milestone_tasks and not all(t.verified for t in milestone_tasks):
                current_milestone = m
                break
        if current_milestone:
            m_tasks = [t for t in plan.tasks if t.id in current_milestone.task_ids]
            m_done = sum(1 for t in m_tasks if t.verified)
            lines.append(
                f"**Current Milestone:** {current_milestone.title} ({m_done}/{len(m_tasks)})"
            )
            lines.append("")

    # Show ready tasks (can start now)
    if ready_tasks:
        lines.append(f"**Ready Tasks ({len(ready_tasks)}):**")
        for task in ready_tasks[:4]:
            lines.append(f"- `{task.id}`: {task.description}")
        if len(ready_tasks) > 4:
            lines.append(f"- ... and {len(ready_tasks) - 4} more")
        lines.append("")

    # Show parallel opportunity
    if len(parallel_tasks) > 1:
        task_ids = ", ".join(f"`{t.id}`" for t in parallel_tasks[:4])
        lines.append(
            f"**Parallel Opportunity:** {len(parallel_tasks)} tasks can run concurrently: {task_ids}"
        )
        lines.append("")

    # Show blocked tasks
    if blocked_tasks:
        lines.append(f"**Blocked Tasks ({len(blocked_tasks)}):**")
        for task in blocked_tasks[:3]:
            blockers = plan.get_blocking_tasks(task.id)
            blocker_ids = ", ".join(b.id for b in blockers[:2])
            lines.append(
                f"- `{task.id}`: {task.description} [waiting on {blocker_ids}]"
            )
        lines.append("")

    # Show workflow reminder based on state
    if incomplete_tasks:
        lines.append(
            "**Workflow:** Implement → `complete_plan_task` → Run tests → `verify_plan_task`"
        )
    elif unverified_tasks:
        lines.append(
            f"**Action Required:** {len(unverified_tasks)} task(s) need verification before plan completion"
        )
    else:
        lines.append(
            f'**Ready:** All tasks verified! Call `complete_plan("{plan.id}")` to finish.'
        )

    lines.append("</current_plan_state>")

    return "\n".join(lines)


def get_active_plan_reminder(context: "AgentContext") -> str | None:
    """Check if there's an in-progress plan with work remaining and return a reminder.

    This is called by the agent loop to remind the agent to continue working on plans.
    Uses context.active_plan_id if set, otherwise falls back to project-scoped lookup.

    Args:
        context: The agent context

    Returns:
        A reminder string if there's an active plan with work, None otherwise
    """
    plan_manager = _get_plan_manager(context)

    # First check for session-specific active plan
    plan = None
    if context.active_plan_id:
        plan = plan_manager.get_plan(context.active_plan_id)
        if plan and plan.status != PlanStatus.IN_PROGRESS:
            plan = None

    # Fallback to most recent IN_PROGRESS plan for this project
    if plan is None:
        root_dir = _get_root_dir(context)
        active_plans = plan_manager.list_active_plans(root_dir=root_dir)
        in_progress = [p for p in active_plans if p.status == PlanStatus.IN_PROGRESS]
        if in_progress:
            plan = in_progress[0]

    if plan is None:
        return None

    incomplete_tasks = plan.get_incomplete_tasks()
    unverified_tasks = plan.get_unverified_tasks()

    # No work remaining
    if not incomplete_tasks and not unverified_tasks:
        return None

    # Build status summary
    total = len(plan.tasks)
    completed = len([t for t in plan.tasks if t.completed])
    verified = len([t for t in plan.tasks if t.verified])

    reminder = f"""📋 **Active Plan Reminder**

**Plan:** {plan.title} (`{plan.id}`)
**Progress:** {completed}/{total} completed, {verified}/{total} verified
"""

    # Prioritize incomplete tasks over unverified
    if incomplete_tasks:
        next_task = incomplete_tasks[0]
        reminder += f"""
**Next task:** `{next_task.id}` - {next_task.description}"""

        if next_task.files:
            reminder += f"\n**Files:** {', '.join(next_task.files)}"

        if next_task.details:
            reminder += f"\n**Details:** {next_task.details}"

        reminder += f"""

**Workflow:**
1. Implement the task
2. Call `complete_plan_task("{plan.id}", "{next_task.id}")`
3. Run tests
4. Call `verify_plan_task("{plan.id}", "{next_task.id}", "<test results>")`
"""
        if next_task.tests:
            reminder += f"\n**Testing approach:** {next_task.tests}"

    elif unverified_tasks:
        # All tasks completed but some not verified
        reminder += f"""
⚠️ **{len(unverified_tasks)} task(s) need verification:**
"""
        for task in unverified_tasks[:3]:
            reminder += f"- ✅ `{task.id}`: {task.description}\n"

        reminder += f"""
Run tests and call `verify_plan_task("{plan.id}", "<task_id>", "<test results>")` for each.
When all verified, call `complete_plan("{plan.id}")`.
"""

    return reminder


def get_task_completion_hint(
    context: "AgentContext", modified_files: list[str]
) -> str | None:
    """Check if modified files match any incomplete tasks and return a hint.

    This is called after file-modifying tools to remind the agent to mark tasks complete.
    Uses context.active_plan_id if set, otherwise falls back to project-scoped lookup.

    Args:
        context: The agent context
        modified_files: List of file paths that were modified

    Returns:
        A hint string if files match a task, None otherwise
    """
    if not modified_files:
        return None

    plan_manager = _get_plan_manager(context)

    # First check for session-specific active plan
    plan = None
    if context.active_plan_id:
        plan = plan_manager.get_plan(context.active_plan_id)
        if plan and plan.status != PlanStatus.IN_PROGRESS:
            plan = None

    # Fallback to most recent IN_PROGRESS plan for this project
    if plan is None:
        root_dir = _get_root_dir(context)
        active_plans = plan_manager.list_active_plans(root_dir=root_dir)
        in_progress = [p for p in active_plans if p.status == PlanStatus.IN_PROGRESS]
        if in_progress:
            plan = in_progress[0]

    if plan is None:
        return None

    # Normalize modified files for comparison
    modified_set = set()
    for f in modified_files:
        # Handle both absolute and relative paths
        path = Path(f)
        modified_set.add(path.name)  # Just filename
        modified_set.add(str(path))  # Full path as given
        if path.is_absolute():
            try:
                modified_set.add(str(path.relative_to(Path.cwd())))
            except ValueError:
                pass

    # Check plan for matching incomplete tasks
    for task in plan.get_incomplete_tasks():
        if not task.files:
            continue

        # Check if any task files match modified files
        for task_file in task.files:
            task_path = Path(task_file)
            if task_path.name in modified_set or task_file in modified_set:
                hint = f"""💡 **Task Hint:** You modified `{modified_files[0]}` which is part of task `{task.id}` ({task.description}).

**Next steps:**
1. Complete the task: `complete_plan_task("{plan.id}", "{task.id}")`
2. Run tests to verify
3. Verify the task: `verify_plan_task("{plan.id}", "{task.id}", "<test results>")`"""
                if task.tests:
                    hint += f"\n\n**Testing approach:** {task.tests}"
                return hint

    # Also check for completed but unverified tasks
    for task in plan.get_unverified_tasks():
        if not task.files:
            continue

        for task_file in task.files:
            task_path = Path(task_file)
            if task_path.name in modified_set or task_file in modified_set:
                return f"""💡 **Verification Reminder:** Task `{task.id}` ({task.description}) is completed but not verified.

Run tests and call: `verify_plan_task("{plan.id}", "{task.id}", "<test results>")`"""

    return None


def _record_metrics_baseline(plan: "Plan", context: "AgentContext") -> None:
    """Record cost baseline when plan execution starts.

    This captures the current token/cost totals from the agent context
    so we can calculate deltas during plan execution.

    Args:
        plan: The plan to record baseline for
        context: Agent context with usage information
    """
    from datetime import datetime, timezone

    # Get current usage from context
    usage = context.usage_summary()

    # Record baseline in plan metrics
    plan.metrics.execution_started_at = datetime.now(timezone.utc)
    plan.metrics.baseline_input_tokens = usage.get("total_input_tokens", 0)
    plan.metrics.baseline_output_tokens = usage.get("total_output_tokens", 0)
    plan.metrics.baseline_thinking_tokens = usage.get("total_thinking_tokens", 0)
    plan.metrics.baseline_cached_tokens = usage.get("cached_tokens", 0)
    plan.metrics.baseline_cost_dollars = usage.get("total_cost", 0.0)


def _get_cost_delta(plan: "Plan", context: "AgentContext") -> dict:
    """Get the cost delta since plan execution started.

    Args:
        plan: The plan with baseline metrics
        context: Agent context with current usage

    Returns:
        Dict with delta values for tokens and cost
    """
    usage = context.usage_summary()

    return {
        "input_tokens": usage.get("total_input_tokens", 0)
        - plan.metrics.baseline_input_tokens,
        "output_tokens": usage.get("total_output_tokens", 0)
        - plan.metrics.baseline_output_tokens,
        "thinking_tokens": usage.get("total_thinking_tokens", 0)
        - plan.metrics.baseline_thinking_tokens,
        "cached_tokens": usage.get("cached_tokens", 0)
        - plan.metrics.baseline_cached_tokens,
        "cost_dollars": usage.get("total_cost", 0.0)
        - plan.metrics.baseline_cost_dollars,
    }


def _run_capture_command(command: str, timeout: int = 30) -> tuple[bool, str]:
    """Run a metric capture command and return the output.

    Args:
        command: Shell command to run
        timeout: Timeout in seconds

    Returns:
        Tuple of (success: bool, output_or_error: str)
    """
    import subprocess

    if not command:
        return False, "No capture command defined"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return False, f"Command failed (exit {result.returncode}): {result.stderr}"
        return True, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except Exception as e:
        return False, f"Command error: {str(e)}"


def _parse_metric_value(output: str, metric_type: str) -> float:
    """Parse command output into a metric value.

    Args:
        output: Raw command output
        metric_type: Expected type ("int", "float", "percent")

    Returns:
        Parsed numeric value

    Raises:
        ValueError: If output cannot be parsed
    """
    # Strip whitespace and handle empty output
    output = output.strip()
    if not output:
        raise ValueError("Empty output")

    # For percent, strip % suffix if present
    if metric_type == "percent" and output.endswith("%"):
        output = output[:-1].strip()

    # Parse based on type
    if metric_type == "int":
        return float(int(output))
    else:  # float or percent
        return float(output)


def capture_metric_snapshot(
    plan: Plan,
    context: "AgentContext",
    trigger: str,
) -> MetricSnapshot:
    """Capture a metric snapshot for the plan.

    Captures current cost delta, runs capture commands for all defined
    metrics, and records version information.

    Args:
        plan: The plan to capture metrics for
        context: Agent context with usage information
        trigger: What triggered this snapshot (e.g., "plan_start", "task_complete:abc")

    Returns:
        The created MetricSnapshot (also added to plan.metrics.snapshots)
    """
    from datetime import datetime, timezone

    from silica.developer.plans import (
        MetricSnapshot,
        get_agent_version,
        get_silica_version,
    )

    # Calculate wall clock time since execution started
    wall_clock_seconds = 0.0
    if plan.metrics.execution_started_at:
        delta = datetime.now(timezone.utc) - plan.metrics.execution_started_at
        wall_clock_seconds = delta.total_seconds()

    # Get cost delta
    cost_delta = _get_cost_delta(plan, context)

    # Capture custom metrics
    metrics: dict[str, float] = {}
    metric_errors: dict[str, str] = {}

    for definition in plan.metrics.definitions:
        if not definition.validated or not definition.capture_command:
            # Skip unvalidated metrics
            metric_errors[definition.name] = "Not validated"
            continue

        success, output = _run_capture_command(definition.capture_command)
        if success:
            try:
                value = _parse_metric_value(output, definition.metric_type)
                metrics[definition.name] = value
            except ValueError as e:
                metric_errors[definition.name] = f"Parse error: {e} (output: {output})"
        else:
            metric_errors[definition.name] = output

    # Create snapshot
    snapshot = MetricSnapshot(
        timestamp=datetime.now(timezone.utc),
        wall_clock_seconds=wall_clock_seconds,
        trigger=trigger,
        input_tokens=cost_delta["input_tokens"],
        output_tokens=cost_delta["output_tokens"],
        thinking_tokens=cost_delta["thinking_tokens"],
        cached_tokens=cost_delta["cached_tokens"],
        cost_dollars=cost_delta["cost_dollars"],
        agent_version=get_agent_version(),
        silica_version=get_silica_version(),
        metrics=metrics,
        metric_errors=metric_errors,
    )

    # Add to plan's snapshots
    plan.metrics.snapshots.append(snapshot)

    return snapshot


def _generate_metrics_feedback(plan: Plan, snapshot: MetricSnapshot) -> str:
    """Generate a feedback message showing metric changes.

    Shows current values, delta from previous snapshot, delta from start,
    and progress toward targets. Highlights regressions.

    Args:
        plan: The plan with metric definitions
        snapshot: The just-captured snapshot

    Returns:
        Formatted feedback message
    """
    if not plan.metrics.definitions:
        return ""

    lines = [
        f"📊 **Metrics Snapshot** ({snapshot.trigger})",
        "━" * 50,
        "",
    ]

    # Get previous and start snapshots for comparison
    snapshots = plan.metrics.snapshots
    prev_snapshot = None
    start_snapshot = None

    for s in snapshots:
        if s.trigger == "plan_start":
            start_snapshot = s
        if s != snapshot:
            prev_snapshot = s  # Will end up being the one before current

    # Build metrics table
    has_metrics = False
    regressions = []
    on_track = []

    for definition in plan.metrics.definitions:
        if not definition.validated:
            continue

        name = definition.name
        direction = definition.direction
        target = definition.target_value

        # Get current value
        if name in snapshot.metrics:
            current = snapshot.metrics[name]
            has_metrics = True
        elif name in snapshot.metric_errors:
            lines.append(f"⚠️ **{name}**: {snapshot.metric_errors[name]}")
            continue
        else:
            continue

        # Calculate deltas
        delta_prev = ""
        delta_start = ""
        is_regression = False

        if prev_snapshot and name in prev_snapshot.metrics:
            prev_val = prev_snapshot.metrics[name]
            diff = current - prev_val
            if diff != 0:
                sign = "+" if diff > 0 else ""
                delta_prev = (
                    f"{sign}{diff:.1f}"
                    if isinstance(diff, float)
                    else f"{sign}{int(diff)}"
                )

                # Check for regression based on direction
                if direction == "up" and diff < 0:
                    is_regression = True
                    delta_prev += " ⚠️"
                elif direction == "down" and diff > 0:
                    is_regression = True
                    delta_prev += " ⚠️"
                else:
                    delta_prev += " ✓"

        if start_snapshot and name in start_snapshot.metrics:
            start_val = start_snapshot.metrics[name]
            diff = current - start_val
            if diff != 0:
                sign = "+" if diff > 0 else ""
                delta_start = (
                    f"{sign}{diff:.1f}"
                    if isinstance(diff, float)
                    else f"{sign}{int(diff)}"
                )

        # Calculate progress toward target
        progress = ""
        if target is not None:
            if direction == "up":
                if target != 0:
                    pct = (current / target) * 100
                    progress = f"{pct:.1f}%"
            else:  # direction == "down"
                if start_snapshot and name in start_snapshot.metrics:
                    start_val = start_snapshot.metrics[name]
                    if start_val != 0:
                        # Progress = how much we've reduced from start
                        pct = ((start_val - current) / start_val) * 100
                        progress = f"{pct:.1f}%"

        # Format direction indicator
        dir_indicator = "↑" if direction == "up" else "↓"

        # Build line
        current_str = (
            f"{current:.1f}"
            if isinstance(current, float) and not current.is_integer()
            else str(int(current))
        )
        target_str = str(int(target)) if target is not None else "-"

        lines.append(
            f"| {name} {dir_indicator} | {current_str} | {delta_prev or '-'} | {delta_start or '-'} | {target_str} | {progress or '-'} |"
        )

        if is_regression:
            regressions.append(name)
        elif delta_prev and "✓" in delta_prev:
            on_track.append(name)

    if has_metrics:
        # Insert table header before metrics
        header_idx = 3  # After the title and separator
        lines.insert(
            header_idx, "| Metric | Current | Δ Prev | Δ Start | Target | Progress |"
        )
        lines.insert(
            header_idx + 1,
            "|--------|---------|--------|---------|--------|----------|",
        )

    # Add cost summary
    lines.append("")
    cost_str = (
        f"${snapshot.cost_dollars:.4f}"
        if snapshot.cost_dollars < 1
        else f"${snapshot.cost_dollars:.2f}"
    )
    tokens_str = f"{snapshot.input_tokens:,} in, {snapshot.output_tokens:,} out"
    lines.append(f"💰 **Cost**: {cost_str} | Tokens: {tokens_str}")

    # Add time
    mins = int(snapshot.wall_clock_seconds // 60)
    secs = int(snapshot.wall_clock_seconds % 60)
    lines.append(f"⏱️ **Time**: {mins}m {secs}s elapsed")

    # Add regression/progress summary
    if regressions:
        lines.append("")
        lines.append(f"⚠️ **Regression**: {', '.join(regressions)}")
    if on_track:
        lines.append(f"✅ **On track**: {', '.join(on_track)}")

    return "\n".join(lines)


def _get_plan_manager(context: "AgentContext") -> PlanManager:
    """Get or create a PlanManager for the current persona with project awareness."""
    from silica.developer.plans import get_git_root

    if context.history_base_dir is None:
        base_dir = Path.home() / ".silica" / "personas" / "default"
    else:
        base_dir = Path(context.history_base_dir)

    # Get project root for local plan storage
    project_root = None
    if hasattr(context, "sandbox") and context.sandbox is not None:
        if hasattr(context.sandbox, "root_directory"):
            project_root = get_git_root(context.sandbox.root_directory)

    return PlanManager(base_dir, project_root=project_root)


def _get_root_dir(context: "AgentContext") -> str:
    """Get the project root directory from the context.

    Uses the sandbox root if available, otherwise falls back to cwd.
    """
    import os

    if hasattr(context, "sandbox") and context.sandbox is not None:
        if hasattr(context.sandbox, "root_directory"):
            return str(context.sandbox.root_directory)
    return os.getcwd()


@tool(group="Planning")
def enter_plan_mode(
    context: "AgentContext",
    topic: str,
    reason: str = "",
    location: str = "",
) -> str:
    """Enter plan mode for structured planning of complex changes.

    Use this when:
    - A task requires changes to multiple files
    - The implementation approach is unclear
    - You need to clarify requirements with the user
    - The task benefits from explicit documentation

    Plan mode focuses on analysis and planning before making changes.
    You can read files and analyze code, but should avoid making changes
    until the plan is approved and you exit plan mode.

    Args:
        topic: The topic/goal for the plan (becomes the plan title)
        reason: Why entering plan mode is beneficial for this task
        location: Storage location - "local" (project dir) or "global" (persona dir).
                  Defaults to local if in git repo, global otherwise.

    Returns:
        Confirmation message with plan ID and instructions
    """
    plan_manager = _get_plan_manager(context)
    root_dir = _get_root_dir(context)

    # Parse location
    force_location = None
    if location in ("local", "global"):
        force_location = location

    # Create the plan
    plan = plan_manager.create_plan(
        title=topic,
        session_id=context.session_id,
        context=reason if reason else f"Planning: {topic}",
        root_dir=root_dir,
        location=force_location,
    )

    # Store active plan ID in context for session tracking
    context.active_plan_id = plan.id

    result = f"""✅ **Plan Mode Activated**

**Plan ID:** `{plan.id}`
**Title:** {plan.title}

You are now in plan mode. Focus on:
1. **Analyzing** the codebase to understand the current state
2. **Asking clarifying questions** using `ask_clarifications` if requirements are unclear
3. **Documenting** your implementation approach using `update_plan`
4. **Adding tasks** using `add_plan_tasks`

When the plan is complete, use `exit_plan_mode` with:
- `action="submit"` to submit for user review
- `action="save"` to save as draft and exit

**Current plan saved at:** `~/.silica/personas/.../plans/active/{plan.id}.md`
"""
    return result


@tool(group="Planning")
async def ask_clarifications(
    context: "AgentContext",
    plan_id: str,
    questions: str,
) -> str:
    """Ask the user multiple clarifying questions during planning.

    Presents questions as an interactive form with a confirmation step.
    The user can review and edit all answers before final submission.

    Args:
        plan_id: ID of the plan these questions relate to
        questions: JSON array of question objects. Each object has:
            - id: Unique identifier for this question
            - question: The question text
            - type: "text", "choice", or "multi_choice" (default: "text")
            - options: List of options (for choice/multi_choice types)
            - required: Whether an answer is required (default: true)

    Returns:
        JSON object mapping question IDs to user answers, or {"cancelled": true}

    Example:
        questions = '[
            {"id": "auth", "question": "What auth method?", "type": "choice", "options": ["JWT", "OAuth", "API keys"]},
            {"id": "db", "question": "Database preference?", "type": "choice", "options": ["PostgreSQL", "SQLite"]},
            {"id": "notes", "question": "Additional requirements?", "type": "text", "required": false}
        ]'
    """
    # Validate plan exists
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)
    if plan is None:
        return json.dumps({"error": f"Plan {plan_id} not found"})

    # Parse questions
    try:
        questions_list = json.loads(questions)
        if not isinstance(questions_list, list):
            return json.dumps({"error": "questions must be a JSON array"})
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"})

    # Validate question format
    for q in questions_list:
        if not isinstance(q, dict):
            return json.dumps({"error": "Each question must be an object"})
        if "id" not in q:
            return json.dumps({"error": "Each question must have an 'id'"})
        if "question" not in q:
            return json.dumps({"error": "Each question must have a 'question'"})

    # Normalize questions for user_choice format
    normalized = []
    for q in questions_list:
        norm_q = {
            "id": q["id"],
            "prompt": q["question"],
        }
        if q.get("options"):
            norm_q["options"] = q["options"]
        if q.get("type"):
            norm_q["type"] = q["type"]
        if "required" in q:
            norm_q["required"] = q["required"]
        normalized.append(norm_q)

    # Use the user_choice tool's multi-question support
    from silica.developer.tools.user_choice import user_choice

    result = await user_choice(context, json.dumps(normalized))

    # Parse result and store answers in the plan
    try:
        answers = json.loads(result)
        if not answers.get("cancelled"):
            # Store answers in the plan
            for q in questions_list:
                q_id = q["id"]
                if q_id in answers:
                    # Add question and answer to plan
                    plan_q = plan.add_question(
                        question=q["question"],
                        question_type=q.get("type", "text"),
                        options=q.get("options", []),
                    )
                    plan.answer_question(plan_q.id, answers[q_id])

            plan.add_progress(f"Clarified {len(answers)} questions with user")
            plan_manager.update_plan(plan)
    except json.JSONDecodeError:
        pass

    return result


@tool(group="Planning")
def update_plan(
    context: "AgentContext",
    plan_id: str,
    section: str,
    content: str,
) -> str:
    """Update a section of a plan.

    Args:
        plan_id: ID of the plan to update
        section: Section name - one of: "context", "approach", "considerations"
        content: New content for the section

    Returns:
        Confirmation message
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)

    if plan is None:
        return f"Error: Plan {plan_id} not found"

    valid_sections = ["context", "approach", "considerations"]
    if section not in valid_sections:
        return f"Error: Invalid section '{section}'. Valid sections: {', '.join(valid_sections)}"

    if section == "context":
        plan.context = content
    elif section == "approach":
        plan.approach = content
    elif section == "considerations":
        # Parse as key: value pairs or just set as risks
        if ":" in content:
            lines = content.strip().split("\n")
            for line in lines:
                if ":" in line:
                    key, value = line.split(":", 1)
                    plan.considerations[key.strip()] = value.strip()
        else:
            plan.considerations["notes"] = content

    plan.add_progress(f"Updated {section}")
    plan_manager.update_plan(plan)

    return f"✅ Updated '{section}' in plan {plan_id}"


@tool(group="Planning")
def add_plan_tasks(
    context: "AgentContext",
    plan_id: str,
    tasks: str,
) -> str:
    """Add tasks to a plan.

    Args:
        plan_id: ID of the plan
        tasks: JSON array of task objects. Each object has:
            - description: Task description (required)
            - details: Implementation details (optional)
            - files: List of affected files (optional)
            - tests: Testing approach (optional)
            - dependencies: List of task IDs this depends on (optional)

    Returns:
        Confirmation with task IDs

    Example:
        tasks = '[
            {"description": "Create database schema", "files": ["schema.sql"]},
            {"description": "Implement API endpoints", "files": ["api.py"], "tests": "Unit tests"},
            {"description": "Add frontend components", "dependencies": ["task-1", "task-2"]}
        ]'
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)

    if plan is None:
        return f"Error: Plan {plan_id} not found"

    try:
        tasks_list = json.loads(tasks)
        if not isinstance(tasks_list, list):
            return "Error: tasks must be a JSON array"
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON: {e}"

    added_tasks = []
    for task_data in tasks_list:
        if not isinstance(task_data, dict):
            continue
        if "description" not in task_data:
            continue

        task = plan.add_task(
            description=task_data["description"],
            details=task_data.get("details", ""),
            files=task_data.get("files", []),
            tests=task_data.get("tests", ""),
            dependencies=task_data.get("dependencies", []),
        )
        added_tasks.append(task)

    plan.add_progress(f"Added {len(added_tasks)} tasks")
    plan_manager.update_plan(plan)

    result = f"✅ Added {len(added_tasks)} tasks to plan {plan_id}:\n\n"
    for task in added_tasks:
        result += f"- `{task.id}`: {task.description}\n"

    return result


@tool(group="Planning")
def add_milestone(
    context: "AgentContext",
    plan_id: str,
    title: str,
    description: str = "",
    task_ids: str = "",
) -> str:
    """Add a milestone to group related tasks.

    Args:
        plan_id: ID of the plan
        title: Milestone title
        description: Optional description
        task_ids: Optional comma-separated task IDs to assign

    Returns:
        Confirmation with milestone ID
    """
    from silica.developer.plans import Milestone

    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)
    if plan is None:
        return f"Error: Plan {plan_id} not found"

    # Create milestone
    import uuid

    milestone = Milestone(
        id=str(uuid.uuid4())[:8],
        title=title,
        description=description,
        task_ids=[t.strip() for t in task_ids.split(",") if t.strip()]
        if task_ids
        else [],
        order=len(plan.milestones),
    )
    plan.milestones.append(milestone)
    plan.add_progress(f"Added milestone: {title}")
    plan_manager.update_plan(plan)

    return f"✅ Added milestone `{milestone.id}`: {title}"


@tool(group="Planning")
def move_tasks_to_milestone(
    context: "AgentContext",
    plan_id: str,
    milestone_id: str,
    task_ids: str,
) -> str:
    """Assign tasks to a milestone.

    Args:
        plan_id: ID of the plan
        milestone_id: ID of the milestone
        task_ids: Comma-separated task IDs to assign

    Returns:
        Confirmation message
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)
    if plan is None:
        return f"Error: Plan {plan_id} not found"

    milestone = next((m for m in plan.milestones if m.id == milestone_id), None)
    if milestone is None:
        return f"Error: Milestone {milestone_id} not found"

    ids = [t.strip() for t in task_ids.split(",") if t.strip()]
    added = []
    for tid in ids:
        if tid not in milestone.task_ids:
            milestone.task_ids.append(tid)
            added.append(tid)

    plan_manager.update_plan(plan)
    return f"✅ Added {len(added)} tasks to milestone '{milestone.title}'"


@tool(group="Planning")
def add_task_dependency(
    context: "AgentContext",
    plan_id: str,
    task_id: str,
    depends_on: str,
    require_verified: bool = False,
) -> str:
    """Add a dependency to a task.

    Args:
        plan_id: ID of the plan
        task_id: Task that will have the dependency
        depends_on: Task ID that must complete first
        require_verified: If True, dependency must be verified (not just completed)

    Returns:
        Confirmation or error if cycle detected
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)
    if plan is None:
        return f"Error: Plan {plan_id} not found"

    task = plan.get_task_by_id(task_id)
    if task is None:
        return f"Error: Task {task_id} not found"

    if plan.would_create_cycle(task_id, depends_on):
        return "Error: Adding dependency would create a cycle"

    if depends_on not in task.dependencies:
        task.dependencies.append(depends_on)
        task.require_verified_deps = require_verified
        plan_manager.update_plan(plan)

    return f"✅ Task `{task_id}` now depends on `{depends_on}`"


@tool(group="Planning")
def get_ready_tasks(
    context: "AgentContext",
    plan_id: str,
) -> str:
    """Get tasks ready to work on (dependencies satisfied).

    Args:
        plan_id: ID of the plan

    Returns:
        List of ready tasks and parallel opportunities
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)
    if plan is None:
        return f"Error: Plan {plan_id} not found"

    ready = plan.get_ready_tasks()
    blocked = plan.get_blocked_tasks()
    parallel = plan.get_max_parallel_tasks()

    result = f"## Ready Tasks ({len(ready)})\n\n"
    for t in ready:
        result += f"- `{t.id}`: {t.description}\n"

    if len(parallel) > 1:
        result += (
            f"\n**Parallel Opportunity:** {len(parallel)} tasks can run concurrently:\n"
        )
        for t in parallel:
            result += f"- `{t.id}`: {t.description}\n"

    if blocked:
        result += f"\n## Blocked Tasks ({len(blocked)})\n"
        for t in blocked:
            blockers = plan.get_blocking_tasks(t.id)
            blocker_ids = ", ".join(b.id for b in blockers[:3])
            result += f"- `{t.id}`: {t.description} [blocked by {blocker_ids}]\n"

    return result


@tool(group="Planning")
def expand_task(
    context: "AgentContext",
    plan_id: str,
    task_id: str,
    subtasks: str,
) -> str:
    """Break a task into subtasks.

    Args:
        plan_id: ID of the plan
        task_id: Parent task ID to expand
        subtasks: JSON array of subtask descriptions

    Returns:
        Confirmation with subtask IDs
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)
    if plan is None:
        return f"Error: Plan {plan_id} not found"

    parent = plan.get_task_by_id(task_id)
    if parent is None:
        return f"Error: Task {task_id} not found"

    try:
        subtask_list = json.loads(subtasks)
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON: {e}"

    added = []
    for item in subtask_list:
        desc = item if isinstance(item, str) else item.get("description", "")
        if desc:
            task = plan.add_task(description=desc)
            task.parent_task_id = task_id
            added.append(task)

    plan_manager.update_plan(plan)
    result = f"✅ Added {len(added)} subtasks to `{task_id}`:\n"
    for t in added:
        result += f"- `{t.id}`: {t.description}\n"
    return result


@tool(group="Planning")
def add_plan_metrics(
    context: "AgentContext",
    plan_id: str,
    metrics: str,
) -> str:
    """Add metrics to track during plan execution.

    Define what metrics to track for this plan. Capture commands can be
    set later using `define_metric_capture` during the setup phase.

    Args:
        plan_id: ID of the plan
        metrics: JSON array of metric definitions. Each object has:
            - name: Metric name (required, e.g., "tests_passing")
            - direction: "up" (higher is better) or "down" (lower is better)
            - metric_type: "int", "float", or "percent" (default: "int")
            - target_value: Target value to reach (optional)
            - description: Human-readable description (optional)

    Returns:
        Confirmation with added metrics

    Example:
        metrics = '[
            {"name": "tests_passing", "direction": "up", "target_value": 149},
            {"name": "test_failures", "direction": "down", "target_value": 0},
            {"name": "coverage_percent", "direction": "up", "metric_type": "percent", "target_value": 80}
        ]'
    """
    from silica.developer.plans import MetricDefinition

    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)

    if plan is None:
        return f"Error: Plan {plan_id} not found"

    try:
        metrics_list = json.loads(metrics)
        if not isinstance(metrics_list, list):
            return "Error: metrics must be a JSON array"
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON: {e}"

    added_metrics = []
    for metric_data in metrics_list:
        if not isinstance(metric_data, dict):
            continue
        if "name" not in metric_data:
            continue

        # Check for duplicate names
        name = metric_data["name"]
        if any(d.name == name for d in plan.metrics.definitions):
            continue  # Skip duplicates

        definition = MetricDefinition(
            name=name,
            metric_type=metric_data.get("metric_type", "int"),
            direction=metric_data.get("direction", "up"),
            description=metric_data.get("description", ""),
            target_value=metric_data.get("target_value"),
            capture_command="",  # Set later via define_metric_capture
            validated=False,
        )
        plan.metrics.definitions.append(definition)
        added_metrics.append(definition)

    plan.add_progress(f"Added {len(added_metrics)} metrics to track")
    plan_manager.update_plan(plan)

    result = f"✅ Added {len(added_metrics)} metrics to plan {plan_id}:\n\n"
    for metric in added_metrics:
        dir_str = (
            "↑ higher is better" if metric.direction == "up" else "↓ lower is better"
        )
        target_str = (
            f", target: {metric.target_value}"
            if metric.target_value is not None
            else ""
        )
        result += f"- **{metric.name}** ({metric.metric_type}, {dir_str}{target_str})\n"

    result += "\n⚠️ **Next:** Use `define_metric_capture` to set capture commands for each metric."
    result += "\nMetrics must be validated before plan execution starts."

    return result


@tool(group="Planning")
def define_metric_capture(
    context: "AgentContext",
    plan_id: str,
    metric_name: str,
    capture_command: str,
) -> str:
    """Define and validate the capture command for a metric.

    Runs the command to validate it works and shows the captured value.
    The metric must have been declared using `add_plan_metrics` first.

    Args:
        plan_id: ID of the plan
        metric_name: Name of the metric to configure
        capture_command: Shell command that outputs the metric value

    Returns:
        Validation result with current metric value

    Example:
        define_metric_capture(
            plan_id="abc123",
            metric_name="tests_passing",
            capture_command="./run_tests.sh 2>&1 | grep -oP '\\d+(?= passed)'"
        )
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)

    if plan is None:
        return f"Error: Plan {plan_id} not found"

    # Find the metric
    metric = None
    for d in plan.metrics.definitions:
        if d.name == metric_name:
            metric = d
            break

    if metric is None:
        return f"Error: Metric '{metric_name}' not found in plan. Use `add_plan_metrics` to declare it first."

    # Run the capture command to validate
    success, output = _run_capture_command(capture_command)
    if not success:
        return f"❌ **Capture command failed:**\n\n```\n{output}\n```\n\nPlease fix the command and try again."

    # Parse the output
    try:
        value = _parse_metric_value(output, metric.metric_type)
    except ValueError as e:
        return f"❌ **Could not parse output as {metric.metric_type}:**\n\nOutput: `{output}`\nError: {e}\n\nThe command should output a single numeric value."

    # Update the metric definition
    metric.capture_command = capture_command
    metric.validated = True
    plan_manager.update_plan(plan)

    # Build response
    dir_str = "higher" if metric.direction == "up" else "lower"
    result = f"""✅ **Metric '{metric_name}' configured successfully**

**Command:** `{capture_command}`
**Current value:** {value}
**Direction:** {dir_str} is better
"""
    if metric.target_value is not None:
        result += f"**Target:** {metric.target_value}\n"

    # Check how many metrics still need configuration
    unvalidated = [d for d in plan.metrics.definitions if not d.validated]
    if unvalidated:
        result += f"\n⚠️ **{len(unvalidated)} metrics still need configuration:**\n"
        for d in unvalidated:
            result += f"- {d.name}\n"
    else:
        result += "\n✅ **All metrics configured!** Ready for plan execution."

    return result


@tool(group="Planning")
def capture_plan_metrics(
    context: "AgentContext",
    plan_id: str,
    note: str = "",
) -> str:
    """Manually capture a metrics snapshot.

    Use this to check progress at any point during task execution,
    not just at task completion milestones. Useful for:
    - Checking if a fix improved metrics before committing
    - Monitoring progress during long-running tasks
    - Debugging metric capture commands

    Args:
        plan_id: ID of the plan
        note: Optional note to include in the snapshot trigger

    Returns:
        Metrics feedback showing current values and changes
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)

    if plan is None:
        return f"Error: Plan {plan_id} not found"

    if not plan.metrics.definitions:
        return "No metrics defined for this plan. Use `add_plan_metrics` to define metrics to track."

    # Check if any metrics are validated
    validated = [d for d in plan.metrics.definitions if d.validated]
    if not validated:
        unvalidated = [d.name for d in plan.metrics.definitions]
        return f"No metrics are configured yet. Use `define_metric_capture` to configure: {', '.join(unvalidated)}"

    # Capture snapshot
    trigger = f"manual:{note}" if note else "manual"
    snapshot = capture_metric_snapshot(plan, context, trigger)
    plan_manager.update_plan(plan)

    # Generate feedback
    feedback = _generate_metrics_feedback(plan, snapshot)

    return f"📸 **Manual Metrics Capture**\n\n{feedback}"


@tool(group="Planning")
def read_plan(
    context: "AgentContext",
    plan_id: str,
) -> str:
    """Read the current state of a plan.

    Args:
        plan_id: ID of the plan to read

    Returns:
        Full plan content as markdown
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)

    if plan is None:
        return f"Error: Plan {plan_id} not found"

    return plan.to_markdown()


@tool(group="Planning")
def list_plans(
    context: "AgentContext",
    include_completed: bool = False,
) -> str:
    """List available plans for the current project.

    Args:
        include_completed: Whether to include completed/abandoned plans

    Returns:
        Formatted list of plans for this project
    """
    plan_manager = _get_plan_manager(context)
    root_dir = _get_root_dir(context)

    active = plan_manager.list_active_plans(root_dir=root_dir)
    result = "## Active Plans\n\n"

    if active:
        for plan in active:
            result += f"- `{plan.id}` - **{plan.title}** ({plan.status.value})\n"
            result += f"  Updated: {plan.updated_at.strftime('%Y-%m-%d %H:%M')}\n"
    else:
        result += "_No active plans for this project_\n"

    if include_completed:
        completed = plan_manager.list_completed_plans(limit=5, root_dir=root_dir)
        result += "\n## Completed Plans (recent)\n\n"
        if completed:
            for plan in completed:
                result += f"- `{plan.id}` - **{plan.title}** ({plan.status.value})\n"
        else:
            result += "_No completed plans for this project_\n"

    return result


@tool(group="Planning")
def exit_plan_mode(
    context: "AgentContext",
    plan_id: str,
    action: str = "save",
) -> str:
    """Exit plan mode.

    Args:
        plan_id: ID of the current plan
        action: One of:
            - "save": Save draft and return to normal mode
            - "submit": Submit plan for user review/approval
            - "execute": Begin execution immediately (requires prior approval)
            - "abandon": Abandon the plan

    Returns:
        Confirmation message
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)

    if plan is None:
        return f"Error: Plan {plan_id} not found"

    valid_actions = ["save", "submit", "execute", "abandon"]
    if action not in valid_actions:
        return f"Error: Invalid action '{action}'. Valid actions: {', '.join(valid_actions)}"

    # Handle actions that should clear active plan (abandon only)
    # Note: save/submit/execute keep the plan active

    if action == "save":
        plan.add_progress("Plan mode exited (saved as draft)")
        plan_manager.update_plan(plan)
        return f"""✅ **Plan Mode Exited**

Plan `{plan_id}` saved as draft.

You can resume planning later with `enter_plan_mode` and reference this plan,
or use `read_plan` to review its contents.
"""

    elif action == "submit":
        if plan.status != PlanStatus.DRAFT:
            return f"Error: Can only submit plans in DRAFT status (current: {plan.status.value})"

        plan_manager.submit_for_review(plan_id)

        # Build a summary for the user
        task_summary = ""
        if plan.tasks:
            task_summary = "\n**Tasks:**\n"
            for t in plan.tasks[:5]:
                task_summary += f"- {t.description}\n"
            if len(plan.tasks) > 5:
                task_summary += f"- ... and {len(plan.tasks) - 5} more\n"

        return f"""📋 **Plan Submitted for Review**

Plan `{plan_id}`: **{plan.title}**

{plan.approach[:500] if plan.approach else "_No approach documented._"}
{task_summary}
---

The plan is ready for your review. Options:
- `/plan approve` - Approve and start execution
- `/plan approve --shelve` - Approve for remote execution later
- `/plan reject [feedback]` - Request changes
- `/plan view` - See full plan details

**Awaiting your decision.**
"""

    elif action == "execute":
        if plan.status == PlanStatus.APPROVED:
            plan_manager.start_execution(plan_id)

            # Re-fetch plan after status change, then record metrics baseline
            plan = plan_manager.get_plan(plan_id)
            _record_metrics_baseline(plan, context)

            # Capture initial snapshot if metrics are defined and validated
            if plan.metrics.definitions:
                has_validated = any(d.validated for d in plan.metrics.definitions)
                if has_validated:
                    capture_metric_snapshot(plan, context, "plan_start")

            plan_manager.update_plan(plan)

            incomplete_tasks = plan.get_incomplete_tasks()

            # Build detailed task list with files
            task_lines = []
            for t in incomplete_tasks[:5]:
                task_lines.append(f"- `{t.id}`: {t.description}")
                if t.files:
                    task_lines.append(f"  Files: {', '.join(t.files)}")
                if t.details:
                    task_lines.append(f"  Details: {t.details[:100]}...")
            task_list = "\n".join(task_lines)

            if len(incomplete_tasks) > 5:
                task_list += f"\n- ... and {len(incomplete_tasks) - 5} more tasks"

            # Get first task for immediate action
            first_task = incomplete_tasks[0] if incomplete_tasks else None
            next_action = ""
            if first_task:
                next_action = f"""
**Start with task `{first_task.id}`:** {first_task.description}
"""
                if first_task.files:
                    next_action += f"Files to modify: {', '.join(first_task.files)}\n"

            return f"""🚀 **Plan Execution Started**

Plan `{plan_id}`: {plan.title}

Status changed to IN_PROGRESS.

**Tasks to complete ({len(incomplete_tasks)} total):**
{task_list}
{next_action}
After completing each task, call `complete_plan_task("{plan_id}", "<task_id>")`.
When all tasks are done, call `complete_plan("{plan_id}")`.
"""
        elif plan.status == PlanStatus.DRAFT:
            return "Error: Plan must be approved before execution. Use action='submit' first."
        elif plan.status == PlanStatus.IN_REVIEW:
            return "Error: Plan is awaiting user approval. Cannot execute yet."
        else:
            return f"Error: Cannot execute plan in {plan.status.value} status."

    elif action == "abandon":
        plan_manager.abandon_plan(plan_id)
        # Clear active plan from context when abandoning
        context.active_plan_id = None
        return f"""🗑️ **Plan Abandoned**

Plan `{plan_id}` has been archived. You can start fresh with a new plan.
"""


@tool(group="Planning")
def submit_for_approval(
    context: "AgentContext",
    plan_id: str,
) -> str:
    """Submit the plan for user approval.

    Call this when you've finished planning and are ready for the user to review.
    The plan should have:
    - Clear context explaining the problem/goal
    - A documented implementation approach
    - Tasks broken down into actionable items

    After submission, control returns to the user who can:
    - Approve the plan for execution
    - Approve and shelve for remote execution
    - Reject with feedback for revisions

    Args:
        plan_id: ID of the plan to submit

    Returns:
        Summary of the plan for user review
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)

    if plan is None:
        return f"Error: Plan {plan_id} not found"

    if plan.status != PlanStatus.DRAFT:
        return f"Error: Can only submit plans in DRAFT status (current: {plan.status.value})"

    # Validate plan has minimum content
    warnings = []
    if not plan.approach:
        warnings.append("⚠️ No implementation approach documented")
    if not plan.tasks:
        warnings.append("⚠️ No tasks defined")

    plan_manager.submit_for_review(plan_id)

    # Build a summary for the user
    task_summary = ""
    if plan.tasks:
        task_summary = "\n**Tasks:**\n"
        for t in plan.tasks[:5]:
            task_summary += f"- {t.description}\n"
        if len(plan.tasks) > 5:
            task_summary += f"- ... and {len(plan.tasks) - 5} more\n"

    warning_text = "\n".join(warnings) + "\n" if warnings else ""

    return f"""📋 **Plan Submitted for Review**

Plan `{plan_id}`: **{plan.title}**

{warning_text}**Approach:**
{plan.approach[:500] if plan.approach else "_No approach documented._"}
{task_summary}
---

The plan is ready for your review. Options:
- `/plan approve` - Approve and start execution
- `/plan approve --shelve` - Approve for remote execution later
- `/plan reject [feedback]` - Request changes
- `/plan view` - See full plan details

**Awaiting your decision.**
"""


@tool(group="Planning")
def link_plan_pr(
    context: "AgentContext",
    plan_id: str,
    pull_request: str,
) -> str:
    """Link a pull request to a plan.

    Call this after creating a PR for the plan's work to track
    the association.

    Args:
        plan_id: The plan ID
        pull_request: PR reference (e.g., "#123", "https://github.com/org/repo/pull/123")

    Returns:
        Confirmation message
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)

    if not plan:
        return f"❌ Plan `{plan_id}` not found."

    plan.pull_request = pull_request
    plan.add_progress(f"Linked to PR: {pull_request}")
    plan_manager.update_plan(plan)

    return f"✅ Plan `{plan_id}` linked to {pull_request}"


@tool(group="Planning")
def complete_plan_task(
    context: "AgentContext",
    plan_id: str,
    task_id: str,
    notes: str = "",
) -> str:
    """Mark a task in a plan as completed (implementation done).

    This marks the task as complete, but it still needs to be verified.
    After completing a task, run tests and use `verify_plan_task` to confirm
    the implementation is correct.

    Args:
        plan_id: ID of the plan
        task_id: ID of the task to complete
        notes: Optional notes about completion

    Returns:
        Confirmation with reminder to verify
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)

    if plan is None:
        return f"Error: Plan {plan_id} not found"

    # Find the task to get its test info
    task = plan.get_task_by_id(task_id)
    if task is None:
        return f"Error: Task {task_id} not found in plan {plan_id}"

    # Warn if dependencies not satisfied (but allow completion)
    dep_warning = ""
    if task.dependencies:
        blocking = plan.get_blocking_tasks(task_id)
        if blocking:
            blocker_ids = ", ".join(f"`{b.id}`" for b in blocking)
            dep_warning = (
                f"\n⚠️ **Warning:** Dependencies not satisfied: {blocker_ids}\n"
            )

    if not plan.complete_task(task_id):
        return f"Error: Could not complete task {task_id}"

    # Auto-complete parent task if all subtasks are complete
    auto_complete_msg = ""
    if task.parent_task_id:
        parent = plan.get_task_by_id(task.parent_task_id)
        if (
            parent
            and not parent.completed
            and plan.are_all_subtasks_complete(parent.id)
        ):
            plan.complete_task(parent.id)
            auto_complete_msg = (
                f"\n✨ Parent task `{parent.id}` auto-completed (all subtasks done)\n"
            )

    if notes:
        plan.add_progress(f"Completed task {task_id}: {notes}")
    else:
        plan.add_progress(f"Completed task {task_id}")

    # Capture metrics snapshot if metrics are configured
    metrics_feedback = ""
    if plan.metrics.definitions and any(d.validated for d in plan.metrics.definitions):
        snapshot = capture_metric_snapshot(plan, context, f"task_complete:{task_id}")
        metrics_feedback = _generate_metrics_feedback(plan, snapshot)

    plan_manager.update_plan(plan)

    # Build verification reminder
    verify_hint = f"""
⚠️ **Next: Verify this task**
Run tests to confirm the implementation is correct, then call:
`verify_plan_task("{plan_id}", "{task_id}", "<test results>")`
"""
    if task and task.tests:
        verify_hint += f"\n**Testing approach:** {task.tests}"

    remaining = plan.get_incomplete_tasks()
    unverified = plan.get_unverified_tasks()

    status = f"✅ Task `{task_id}` marked as **completed** (implementation done).{dep_warning}{auto_complete_msg}\n{verify_hint}"

    if remaining:
        remaining_list = "\n".join(
            f"- ⬜ `{t.id}`: {t.description}" for t in remaining[:3]
        )
        status += f"\n\n**Remaining tasks ({len(remaining)}):**\n{remaining_list}"

    if unverified and len(unverified) > 1:  # More than just the current task
        status += f"\n\n**Unverified tasks ({len(unverified)}):** Remember to verify completed tasks!"

    # Add metrics feedback if available
    if metrics_feedback:
        status += f"\n\n{metrics_feedback}"

    return status


@tool(group="Planning")
def verify_plan_task(
    context: "AgentContext",
    plan_id: str,
    task_id: str,
    test_results: str,
) -> str:
    """Verify a completed task by confirming tests pass.

    A task must be marked as completed before it can be verified.
    Verification confirms that:
    - Tests pass
    - The implementation meets requirements
    - No regressions were introduced

    Args:
        plan_id: ID of the plan
        task_id: ID of the task to verify
        test_results: Evidence of verification (test output, manual testing notes, etc.)

    Returns:
        Confirmation and remaining unverified tasks
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)

    if plan is None:
        return f"Error: Plan {plan_id} not found"

    # Find the task
    task = None
    for t in plan.tasks:
        if t.id == task_id:
            task = t
            break

    if task is None:
        return f"Error: Task {task_id} not found in plan {plan_id}"

    if not task.completed:
        return f"Error: Task {task_id} must be completed before it can be verified. Use `complete_plan_task` first."

    if task.verified:
        return f"Task {task_id} is already verified."

    if not test_results or not test_results.strip():
        return "Error: test_results is required. Provide evidence of testing (test output, manual verification notes, etc.)"

    if not plan.verify_task(task_id, test_results):
        return f"Error: Could not verify task {task_id}"

    plan.add_progress(f"Verified task {task_id}")

    # Capture metrics snapshot if metrics are configured
    metrics_feedback = ""
    if plan.metrics.definitions and any(d.validated for d in plan.metrics.definitions):
        snapshot = capture_metric_snapshot(plan, context, f"task_verified:{task_id}")
        metrics_feedback = _generate_metrics_feedback(plan, snapshot)

    plan_manager.update_plan(plan)

    # Check remaining work
    incomplete = plan.get_incomplete_tasks()
    unverified = plan.get_unverified_tasks()

    status = f"✓✓ Task `{task_id}` **verified**!\n"

    if incomplete:
        status += f"\n**Incomplete tasks ({len(incomplete)}):**\n"
        for t in incomplete[:3]:
            status += f"- ⬜ `{t.id}`: {t.description}\n"
    elif unverified:
        status += f"\n**Tasks needing verification ({len(unverified)}):**\n"
        for t in unverified[:3]:
            status += f"- ✅ `{t.id}`: {t.description}\n"
    else:
        status += "\n🎉 **All tasks completed and verified!**\n"
        status += f'Use `complete_plan("{plan_id}")` to finish the plan.'

    # Add metrics feedback if available
    if metrics_feedback:
        status += f"\n\n{metrics_feedback}"

    return status


@tool(group="Planning")
def reopen_plan(
    context: "AgentContext",
    plan_id: str,
    reason: str = "",
) -> str:
    """Reopen a completed or abandoned plan.

    Use this when a plan was incorrectly marked as completed, or when
    additional work is needed on a previously completed plan.

    Task completion/verification state is preserved - you can decide
    which tasks need to be redone.

    Args:
        plan_id: ID of the plan to reopen
        reason: Optional reason for reopening (e.g., "incomplete implementation",
                "missed requirements", "tests failing")

    Returns:
        Confirmation message with next steps
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)

    if plan is None:
        return f"Error: Plan {plan_id} not found"

    if plan.status not in (PlanStatus.COMPLETED, PlanStatus.ABANDONED):
        return f"Error: Can only reopen COMPLETED or ABANDONED plans (current: {plan.status.value})"

    if not plan_manager.reopen_plan(plan_id, reason):
        return f"Error: Failed to reopen plan {plan_id}"

    # Set as active plan in context
    context.active_plan_id = plan_id

    # Refresh plan to get updated state
    plan = plan_manager.get_plan(plan_id)

    # Build task summary
    incomplete = plan.get_incomplete_tasks()
    unverified = plan.get_unverified_tasks()
    verified = [t for t in plan.tasks if t.verified]

    task_summary = ""
    if plan.tasks:
        task_summary = "\n\n**Task Status:**\n"
        for t in plan.tasks[:8]:
            if t.verified:
                status = "✓✓"
            elif t.completed:
                status = "✅"
            else:
                status = "⬜"
            task_summary += f"- {status} `{t.id}`: {t.description}\n"
        if len(plan.tasks) > 8:
            task_summary += f"- ... and {len(plan.tasks) - 8} more tasks\n"

    return f"""🔄 **Plan Reopened**

Plan `{plan_id}`: **{plan.title}**

{f"**Reason:** {reason}" if reason else ""}

Status changed to IN_PROGRESS.
{task_summary}
**Summary:** {len(verified)} verified, {len(unverified)} completed but unverified, {len(incomplete)} incomplete

**Next steps:**
1. Review which tasks need to be redone
2. Work through incomplete/unverified tasks
3. Call `complete_plan("{plan_id}")` when finished
"""


@tool(group="Planning")
def complete_plan(
    context: "AgentContext",
    plan_id: str,
    notes: str = "",
) -> str:
    """Mark a plan as completed.

    All tasks must be both completed AND verified before the plan can be completed.

    Args:
        plan_id: ID of the plan to complete
        notes: Completion notes/summary

    Returns:
        Confirmation message
    """
    plan_manager = _get_plan_manager(context)
    plan = plan_manager.get_plan(plan_id)

    if plan is None:
        return f"Error: Plan {plan_id} not found"

    if plan.status not in [PlanStatus.IN_PROGRESS, PlanStatus.APPROVED]:
        return f"Error: Can only complete plans that are APPROVED or IN_PROGRESS (current: {plan.status.value})"

    # Check for incomplete tasks
    incomplete = plan.get_incomplete_tasks()
    if incomplete:
        task_list = "\n".join(f"- ⬜ `{t.id}`: {t.description}" for t in incomplete)
        return f"⚠️ **Cannot complete plan:** {len(incomplete)} tasks are incomplete:\n{task_list}\n\nComplete these tasks first using `complete_plan_task`."

    # Check for unverified tasks
    unverified = plan.get_unverified_tasks()
    if unverified:
        task_list = "\n".join(f"- ✅ `{t.id}`: {t.description}" for t in unverified)
        return f"""⚠️ **Cannot complete plan:** {len(unverified)} tasks are not verified:
{task_list}

Run tests and use `verify_plan_task` for each task to confirm the implementation is correct.
All tasks must be verified before the plan can be completed."""

    # Capture final metrics snapshot before completing
    metrics_feedback = ""
    if plan.metrics.definitions and any(d.validated for d in plan.metrics.definitions):
        snapshot = capture_metric_snapshot(plan, context, "plan_end")
        metrics_feedback = _generate_metrics_feedback(plan, snapshot)
        # Update plan with final snapshot before completing
        plan_manager.update_plan(plan)

    plan_manager.complete_plan(plan_id, notes)

    # Clear active plan from context when completing
    context.active_plan_id = None

    result = f"""🎉 **Plan Completed!**

Plan `{plan_id}`: {plan.title}

{notes if notes else "All tasks completed and verified successfully."}

The plan has been archived to the completed plans directory.
"""

    if metrics_feedback:
        result += f"\n**Final Metrics:**\n{metrics_feedback}"

    return result
