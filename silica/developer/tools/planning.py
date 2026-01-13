"""Planning tools for structured plan mode workflow.

These tools enable the agent to enter a structured planning mode for complex changes,
ask clarifying questions to the user, and manage plan documents.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from silica.developer.tools.framework import tool
from silica.developer.plans import PlanManager, PlanStatus

if TYPE_CHECKING:
    from silica.developer.context import AgentContext


def get_active_plan_status(context: "AgentContext") -> dict | None:
    """Get the status of the most recent active plan for UI display.

    This is used to show plan mode indicators in the prompt.

    Args:
        context: The agent context

    Returns:
        Dict with plan info if there's an active plan, None otherwise:
        {
            "id": str,
            "title": str,
            "status": str,  # "planning" or "executing"
            "incomplete_tasks": int,
            "unverified_tasks": int,
            "verified_tasks": int,
            "total_tasks": int,
        }
    """
    plan_manager = _get_plan_manager(context)
    active_plans = plan_manager.list_active_plans()

    if not active_plans:
        return None

    # Get the most recently updated plan
    plan = active_plans[0]

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

    return {
        "id": plan.id,
        "title": plan.title,
        "status": status,
        "incomplete_tasks": incomplete,
        "unverified_tasks": unverified,
        "verified_tasks": verified,
        "total_tasks": total,
    }


def get_active_plan_id(context: "AgentContext") -> str | None:
    """Get the ID of the most recent active plan.

    This is used for context-aware /plan commands.

    Args:
        context: The agent context

    Returns:
        Plan ID if there's an active plan, None otherwise
    """
    plan_manager = _get_plan_manager(context)
    active_plans = plan_manager.list_active_plans()

    if not active_plans:
        return None

    return active_plans[0].id


def get_ephemeral_plan_state(context: "AgentContext") -> str | None:
    """Generate an ephemeral plan state block for injection into user messages.

    This is injected before cache markers in the last user message to provide
    the agent with current plan state without accumulating in conversation history.

    Only returns content for plans that are IN_PROGRESS (actively being executed).

    Args:
        context: The agent context

    Returns:
        Plan state block as string, or None if no active execution
    """
    plan_manager = _get_plan_manager(context)

    # Only show state for plans being executed
    active_plans = plan_manager.list_active_plans()
    in_progress = [p for p in active_plans if p.status == PlanStatus.IN_PROGRESS]

    if not in_progress:
        return None

    plan = in_progress[0]  # Most recently updated

    # Calculate progress
    total = len(plan.tasks)
    completed = len([t for t in plan.tasks if t.completed])
    verified = len([t for t in plan.tasks if t.verified])

    incomplete_tasks = plan.get_incomplete_tasks()
    unverified_tasks = plan.get_unverified_tasks()

    # Build the state block
    lines = [
        "<current_plan_state>",
        f"**Active Plan:** {plan.title} (`{plan.id}`)",
        f"**Progress:** {verified}✓/{total} verified, {completed}/{total} completed",
        "",
    ]

    # Show current/next task
    if incomplete_tasks:
        next_task = incomplete_tasks[0]
        lines.append(f"**Current Task:** `{next_task.id}` - {next_task.description}")
        if next_task.files:
            lines.append(f"  Files: {', '.join(next_task.files)}")
        if next_task.tests:
            lines.append(f"  Tests: {next_task.tests}")
        lines.append("")

    # Show task summary
    if plan.tasks:
        lines.append("**Tasks:**")
        for task in plan.tasks[:8]:  # Limit to first 8 tasks
            if task.verified:
                status = "✓✓"
            elif task.completed:
                status = "✅"
            else:
                status = "⬜"
            lines.append(f"- {status} `{task.id}`: {task.description}")

        if len(plan.tasks) > 8:
            lines.append(f"- ... and {len(plan.tasks) - 8} more tasks")
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

    Args:
        context: The agent context

    Returns:
        A reminder string if there's an active plan with work, None otherwise
    """
    plan_manager = _get_plan_manager(context)

    # Look for in-progress plans
    active_plans = plan_manager.list_active_plans()
    in_progress = [p for p in active_plans if p.status == PlanStatus.IN_PROGRESS]

    if not in_progress:
        return None

    # Get the most recently updated in-progress plan
    plan = in_progress[0]  # Already sorted by updated_at desc
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

    Args:
        context: The agent context
        modified_files: List of file paths that were modified

    Returns:
        A hint string if files match a task, None otherwise
    """
    if not modified_files:
        return None

    plan_manager = _get_plan_manager(context)

    # Look for in-progress plans
    active_plans = plan_manager.list_active_plans()
    in_progress = [p for p in active_plans if p.status == PlanStatus.IN_PROGRESS]

    if not in_progress:
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

    # Check each in-progress plan for matching tasks
    for plan in in_progress:
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
    for plan in in_progress:
        for task in plan.get_unverified_tasks():
            if not task.files:
                continue

            for task_file in task.files:
                task_path = Path(task_file)
                if task_path.name in modified_set or task_file in modified_set:
                    return f"""💡 **Verification Reminder:** Task `{task.id}` ({task.description}) is completed but not verified.

Run tests and call: `verify_plan_task("{plan.id}", "{task.id}", "<test results>")`"""

    return None


def _get_plan_manager(context: "AgentContext") -> PlanManager:
    """Get or create a PlanManager for the current persona."""
    if context.history_base_dir is None:
        base_dir = Path.home() / ".silica" / "personas" / "default"
    else:
        base_dir = Path(context.history_base_dir)
    return PlanManager(base_dir)


@tool(group="Planning")
def enter_plan_mode(
    context: "AgentContext",
    topic: str,
    reason: str = "",
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

    Returns:
        Confirmation message with plan ID and instructions
    """
    plan_manager = _get_plan_manager(context)

    # Create the plan
    plan = plan_manager.create_plan(
        title=topic,
        session_id=context.session_id,
        context=reason if reason else f"Planning: {topic}",
    )

    # Store active plan ID in context (if supported)
    if hasattr(context, "_active_plan_id"):
        context._active_plan_id = plan.id

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
    """List available plans.

    Args:
        include_completed: Whether to include completed/abandoned plans

    Returns:
        Formatted list of plans
    """
    plan_manager = _get_plan_manager(context)

    active = plan_manager.list_active_plans()
    result = "## Active Plans\n\n"

    if active:
        for plan in active:
            result += f"- `{plan.id}` - **{plan.title}** ({plan.status.value})\n"
            result += f"  Updated: {plan.updated_at.strftime('%Y-%m-%d %H:%M')}\n"
    else:
        result += "_No active plans_\n"

    if include_completed:
        completed = plan_manager.list_completed_plans(limit=5)
        result += "\n## Completed Plans (recent)\n\n"
        if completed:
            for plan in completed:
                result += f"- `{plan.id}` - **{plan.title}** ({plan.status.value})\n"
        else:
            result += "_No completed plans_\n"

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

    # Clear active plan from context
    if hasattr(context, "_active_plan_id"):
        context._active_plan_id = None

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

        return f"""📋 **Plan Submitted for Review**

Plan `{plan_id}`: {plan.title}

The plan has been submitted for user review. The user can:
- `/plan approve {plan_id}` - Approve and allow execution
- `/plan view {plan_id}` - View full plan details
- `/plan abandon {plan_id}` - Abandon the plan

Waiting for user approval before proceeding with implementation.
"""

    elif action == "execute":
        if plan.status == PlanStatus.APPROVED:
            plan_manager.start_execution(plan_id)

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
        return f"""🗑️ **Plan Abandoned**

Plan `{plan_id}` has been archived. You can start fresh with a new plan.
"""


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
    task = None
    for t in plan.tasks:
        if t.id == task_id:
            task = t
            break

    if not plan.complete_task(task_id):
        return f"Error: Task {task_id} not found in plan {plan_id}"

    if notes:
        plan.add_progress(f"Completed task {task_id}: {notes}")
    else:
        plan.add_progress(f"Completed task {task_id}")

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

    status = f"✅ Task `{task_id}` marked as **completed** (implementation done).\n{verify_hint}"

    if remaining:
        remaining_list = "\n".join(
            f"- ⬜ `{t.id}`: {t.description}" for t in remaining[:3]
        )
        status += f"\n\n**Remaining tasks ({len(remaining)}):**\n{remaining_list}"

    if unverified and len(unverified) > 1:  # More than just the current task
        status += f"\n\n**Unverified tasks ({len(unverified)}):** Remember to verify completed tasks!"

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

    return status


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

    plan_manager.complete_plan(plan_id, notes)

    return f"""🎉 **Plan Completed!**

Plan `{plan_id}`: {plan.title}

{notes if notes else "All tasks completed and verified successfully."}

The plan has been archived to the completed plans directory.
"""
