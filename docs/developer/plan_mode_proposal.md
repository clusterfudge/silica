# Plan Mode Proposal for Silica

## Overview

This document proposes adding a "Plan Mode" feature to Silica, inspired by Claude Code's implementation. Plan Mode provides a structured workflow for planning complex changes before execution, emphasizing user collaboration, clarification, and explicit plan documentation.

## Research Summary: Claude Code's Plan Mode

Based on research into Claude Code's implementation:

### Core Characteristics

1. **Read-Only Mode**: The agent operates in a read-only mode during planning, analyzing code without making changes
2. **Four-Phase Workflow**:
   - **Phase 1 - Initial Understanding**: Read code, ask clarifying questions
   - **Phase 2 - Design**: Create implementation approach
   - **Phase 3 - Review**: Ensure alignment with user intentions
   - **Phase 4 - Final Plan**: Write concise, executable plan
3. **Plan File Storage**: Plans are stored as markdown files in a dedicated plans directory
4. **System Prompt Integration**: Plan mode injects specific prompts guiding the agent's behavior
5. **Conversation Survival**: Plans survive `/compact` because they're stored separately from the context window
6. **UI Integration**: Shift+Tab toggles through permission modes, with plan mode being one option

### Key Insights

- The "read-only" behavior is achieved through prompt engineering, not tool restrictions
- Plans are self-edited by the agent using file tools
- The agent can enter/exit plan mode based on a state machine
- Plans serve as documentation AND agent instructions for subsequent execution

## Proposed Silica Implementation

### 1. Plan Storage Structure

Plans will be stored under the persona's directory:

```
~/.silica/personas/{persona}/
├── plans/
│   ├── active/          # Currently active plans
│   │   └── {plan_id}.md
│   ├── completed/       # Archived completed plans
│   │   └── {plan_id}.md
│   └── templates/       # Custom plan templates (optional)
│       └── default.md
├── memory/
├── history/
└── persona.md
```

### 2. Plan File Format

Each plan file follows a structured markdown format:

```markdown
# Plan: {title}

**ID:** {plan_id}
**Created:** {timestamp}
**Status:** draft | in-review | approved | in-progress | completed | abandoned
**Session:** {session_id}

## Context
{Description of the problem/feature being addressed}

## Questions for User
- [ ] {Question 1}
- [ ] {Question 2}

## User Answers
### Question 1
{User's answer}

## Implementation Approach
{High-level approach description}

## Tasks
- [ ] {Task 1}
  - Details: {task details}
  - Files: {affected files}
  - Tests: {testing approach}
- [ ] {Task 2}
  ...

## Considerations
- **Risks:** {potential risks}
- **Dependencies:** {dependencies}
- **Alternatives Considered:** {alternatives}

## Progress Log
- {timestamp}: {progress note}

## Completion Notes
{Final notes after completion}
```

### 3. User-Initiated Plan Mode (`/plan` command)

Add a new CLI command to enter plan mode:

```python
# In toolbox.py - register CLI tool
self.register_cli_tool(
    "plan",
    self._plan,
    "Enter plan mode for structured planning",
)
```

The `/plan` command supports several subcommands:

```
/plan                    # Start a new plan (interactive)
/plan <topic>            # Start a new plan with initial topic
/plan list               # List active plans
/plan view <id>          # View a specific plan
/plan resume <id>        # Resume working on a plan
/plan approve <id>       # Approve a plan for execution
/plan abandon <id>       # Abandon/archive a plan
/plan execute <id>       # Exit plan mode and begin execution
```

### 4. Agent-Initiated Plan Mode (Tool)

Expose plan mode as a tool the agent can invoke:

```python
@tool(group="Planning")
def enter_plan_mode(context: AgentContext, topic: str = None, reason: str = None) -> str:
    """Enter plan mode for structured planning of complex changes.
    
    Use this when:
    - A task requires changes to multiple files
    - The implementation approach is unclear
    - You need to clarify requirements with the user
    - The task benefits from explicit documentation
    
    Args:
        topic: Optional initial topic/goal for the plan
        reason: Why entering plan mode is beneficial
    
    Returns:
        Confirmation message with plan ID and instructions
    """
```

Additional planning tools (all require explicit `plan_id`):

```python
@tool(group="Planning")
def ask_clarifications(
    context: AgentContext, 
    plan_id: str,
    questions: list[dict]
) -> dict:
    """Ask the user multiple clarifying questions during planning.
    
    Presents questions as an interactive form with a confirmation step.
    The user can review and edit all answers before final submission.
    
    Args:
        plan_id: ID of the plan these questions relate to
        questions: List of question objects, each with:
            - id: Unique identifier for this question
            - question: The question text
            - type: "text", "choice", or "multi_choice"
            - options: List of options (for choice/multi_choice types)
            - required: Whether an answer is required (default: True)
            - default: Default value (optional)
    
    Returns:
        Dict mapping question IDs to user answers
    
    Example:
        questions = [
            {
                "id": "auth_method",
                "question": "What authentication method should we use?",
                "type": "choice",
                "options": ["JWT tokens", "Session cookies", "OAuth2", "API keys"]
            },
            {
                "id": "user_storage", 
                "question": "Where should user data be stored?",
                "type": "choice",
                "options": ["PostgreSQL", "MongoDB", "SQLite"]
            },
            {
                "id": "additional_requirements",
                "question": "Any additional requirements or constraints?",
                "type": "text",
                "required": False
            }
        ]
        
        answers = ask_clarifications(ctx, "abc123", questions)
        # Returns: {"auth_method": "JWT tokens", "user_storage": "PostgreSQL", "additional_requirements": "Must support 2FA"}
    """

@tool(group="Planning")
def update_plan(
    context: AgentContext, 
    plan_id: str, 
    section: str, 
    content: str
) -> str:
    """Update a section of a plan.
    
    Args:
        plan_id: ID of the plan to update
        section: Section name (context, approach, tasks, considerations, etc.)
        content: New content for the section
    
    Returns:
        Confirmation message
    """

@tool(group="Planning")
def add_plan_tasks(
    context: AgentContext,
    plan_id: str,
    tasks: list[dict]
) -> str:
    """Add tasks to a plan.
    
    Args:
        plan_id: ID of the plan
        tasks: List of task objects, each with:
            - description: Task description
            - details: Implementation details (optional)
            - files: List of affected files (optional)
            - tests: Testing approach (optional)
            - dependencies: List of task IDs this depends on (optional)
    
    Returns:
        Confirmation with task IDs
    """

@tool(group="Planning")
def read_plan(context: AgentContext, plan_id: str) -> str:
    """Read the current state of a plan.
    
    Args:
        plan_id: ID of the plan to read
    
    Returns:
        Full plan content as markdown
    """

@tool(group="Planning")
def exit_plan_mode(
    context: AgentContext, 
    plan_id: str, 
    action: str = "save"
) -> str:
    """Exit plan mode.
    
    Args:
        plan_id: ID of the current plan
        action: One of:
            - "save": Save draft and return to normal mode
            - "submit": Submit plan for user review/approval
            - "execute": Begin execution immediately (requires prior approval)
    
    Returns:
        Confirmation message
    """
```

### 5. Plan Mode Context Injection

When in plan mode, inject additional system prompt guidance:

```python
def _create_plan_mode_section(plan_id: str, plan_content: str) -> dict:
    """Create the plan mode system section."""
    return {
        "type": "text",
        "text": f"""
## Plan Mode Active

You are currently in **Plan Mode** for plan `{plan_id}`.

**In this mode, you should:**
1. **Analyze** - Read and understand relevant code without making changes
2. **Ask Questions** - Use `ask_clarification` to resolve ambiguities
3. **Design** - Develop a comprehensive implementation approach
4. **Document** - Update the plan with your findings and approach

**You should NOT:**
- Make changes to production code
- Create or modify files outside the plan
- Execute potentially destructive commands

**Current Plan:**
```markdown
{plan_content}
```

When you're confident the plan is complete, use `exit_plan_mode` with action="approve" to mark it ready for user approval.
"""
    }
```

### 6. State Management

Track plan mode state in the AgentContext:

```python
@dataclass
class AgentContext:
    # ... existing fields ...
    plan_mode: bool = False
    active_plan_id: str | None = None
    
    def enter_plan_mode(self, plan_id: str):
        """Enter plan mode for a specific plan."""
        self.plan_mode = True
        self.active_plan_id = plan_id
    
    def exit_plan_mode(self):
        """Exit plan mode."""
        self.plan_mode = False
        self.active_plan_id = None
```

### 7. Plan Manager Class

Create a dedicated manager for plan operations:

```python
# silica/developer/plans.py

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from enum import Enum
import json
import uuid


class PlanStatus(Enum):
    DRAFT = "draft"
    IN_REVIEW = "in-review"
    APPROVED = "approved"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


@dataclass
class PlanTask:
    description: str
    details: str = ""
    files: List[str] = field(default_factory=list)
    tests: str = ""
    completed: bool = False


@dataclass
class ClarificationQuestion:
    question: str
    options: List[str] = field(default_factory=list)
    answer: Optional[str] = None
    answered_at: Optional[datetime] = None


@dataclass
class Plan:
    id: str
    title: str
    status: PlanStatus
    session_id: str
    created_at: datetime
    updated_at: datetime
    context: str = ""
    approach: str = ""
    tasks: List[PlanTask] = field(default_factory=list)
    questions: List[ClarificationQuestion] = field(default_factory=list)
    considerations: dict = field(default_factory=dict)
    progress_log: List[tuple] = field(default_factory=list)
    completion_notes: str = ""
    
    def to_markdown(self) -> str:
        """Render plan as markdown."""
        # ... implementation ...
    
    @classmethod
    def from_markdown(cls, content: str) -> "Plan":
        """Parse plan from markdown."""
        # ... implementation ...


class PlanManager:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.plans_dir = base_dir / "plans"
        self.active_dir = self.plans_dir / "active"
        self.completed_dir = self.plans_dir / "completed"
        
        # Ensure directories exist
        self.active_dir.mkdir(parents=True, exist_ok=True)
        self.completed_dir.mkdir(parents=True, exist_ok=True)
    
    def create_plan(self, title: str, session_id: str, context: str = "") -> Plan:
        """Create a new plan."""
        plan = Plan(
            id=str(uuid.uuid4())[:8],
            title=title,
            status=PlanStatus.DRAFT,
            session_id=session_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            context=context,
        )
        self._save_plan(plan)
        return plan
    
    def get_plan(self, plan_id: str) -> Optional[Plan]:
        """Get a plan by ID."""
        # Check active first, then completed
        for directory in [self.active_dir, self.completed_dir]:
            plan_file = directory / f"{plan_id}.md"
            if plan_file.exists():
                return Plan.from_markdown(plan_file.read_text())
        return None
    
    def update_plan(self, plan: Plan):
        """Update an existing plan."""
        plan.updated_at = datetime.now()
        self._save_plan(plan)
    
    def list_active_plans(self) -> List[Plan]:
        """List all active plans."""
        plans = []
        for plan_file in self.active_dir.glob("*.md"):
            try:
                plans.append(Plan.from_markdown(plan_file.read_text()))
            except Exception:
                pass
        return sorted(plans, key=lambda p: p.updated_at, reverse=True)
    
    def approve_plan(self, plan_id: str) -> bool:
        """Mark a plan as approved for execution."""
        plan = self.get_plan(plan_id)
        if plan and plan.status == PlanStatus.IN_REVIEW:
            plan.status = PlanStatus.APPROVED
            self.update_plan(plan)
            return True
        return False
    
    def complete_plan(self, plan_id: str, notes: str = "") -> bool:
        """Mark a plan as completed and archive it."""
        plan = self.get_plan(plan_id)
        if plan:
            plan.status = PlanStatus.COMPLETED
            plan.completion_notes = notes
            plan.updated_at = datetime.now()
            
            # Move from active to completed
            active_file = self.active_dir / f"{plan_id}.md"
            completed_file = self.completed_dir / f"{plan_id}.md"
            
            completed_file.write_text(plan.to_markdown())
            if active_file.exists():
                active_file.unlink()
            
            return True
        return False
    
    def _save_plan(self, plan: Plan):
        """Save a plan to disk."""
        if plan.status in [PlanStatus.COMPLETED, PlanStatus.ABANDONED]:
            directory = self.completed_dir
        else:
            directory = self.active_dir
        
        plan_file = directory / f"{plan.id}.md"
        plan_file.write_text(plan.to_markdown())
```

### 8. Multi-Question Clarification Workflow

The `ask_clarifications` tool presents an interactive form-style interface for gathering user input on multiple questions at once.

#### User Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  📋 Plan Clarifications (plan-abc123)                           │
│                                                                 │
│  The agent needs your input on 3 questions before proceeding.   │
│  Answer each question, then review before submitting.           │
└─────────────────────────────────────────────────────────────────┘

Question 1 of 3: What authentication method should we use?

  ❯ JWT tokens
    Session cookies  
    OAuth2
    API keys
    [Say something else...]

────────────────────────────────────────────────────────────────────

Question 2 of 3: Where should user data be stored?

  ❯ PostgreSQL
    MongoDB
    SQLite
    [Say something else...]

────────────────────────────────────────────────────────────────────

Question 3 of 3: Any additional requirements or constraints?

  > Must support 2FA and have audit logging_

────────────────────────────────────────────────────────────────────

┌─────────────────────────────────────────────────────────────────┐
│  📝 Review Your Answers                                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. What authentication method should we use?                   │
│     → JWT tokens                                                │
│                                                                 │
│  2. Where should user data be stored?                           │
│     → PostgreSQL                                                │
│                                                                 │
│  3. Any additional requirements or constraints?                 │
│     → Must support 2FA and have audit logging                   │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  [S]ubmit    [E]dit answer    [C]ancel                          │
└─────────────────────────────────────────────────────────────────┘
```

#### Implementation

Extend the `UserInterface` abstract class:

```python
# In user_interface.py

async def get_clarifications(
    self,
    title: str,
    questions: list[dict],
) -> dict[str, Any] | None:
    """Present multiple questions to the user with a confirmation step.
    
    Args:
        title: Title/context for the question set
        questions: List of question objects with:
            - id: Unique identifier
            - question: Question text
            - type: "text", "choice", or "multi_choice"
            - options: List of options (for choice types)
            - required: Whether required (default: True)
            - default: Default value
    
    Returns:
        Dict mapping question IDs to answers, or None if cancelled
    """
```

#### Terminal Implementation (Rich/prompt_toolkit)

```python
# In the terminal UI implementation

async def get_clarifications(
    self,
    title: str,
    questions: list[dict],
) -> dict[str, Any] | None:
    """Interactive multi-question form with review step."""
    from prompt_toolkit import prompt
    from prompt_toolkit.shortcuts import radiolist_dialog, checkboxlist_dialog
    
    answers = {}
    
    # Display header
    self.handle_system_message(
        f"📋 **{title}**\n\n"
        f"The agent needs your input on {len(questions)} question(s).\n"
        f"Answer each question, then review before submitting.",
        markdown=True
    )
    
    # Collect answers for each question
    for idx, q in enumerate(questions, 1):
        q_id = q["id"]
        q_text = q["question"]
        q_type = q.get("type", "text")
        options = q.get("options", [])
        required = q.get("required", True)
        default = q.get("default", "")
        
        self.bare(f"\n**Question {idx} of {len(questions)}:** {q_text}\n")
        
        if q_type == "choice" and options:
            # Single choice with arrow key selection
            answer = await self.get_user_choice(q_text, options)
            answers[q_id] = answer
            
        elif q_type == "multi_choice" and options:
            # Multi-select checkboxes
            answer = await self._get_multi_choice(q_text, options)
            answers[q_id] = answer
            
        else:  # text input
            answer = await self.get_user_input(f"  > ")
            if not answer and required:
                # Re-prompt for required fields
                while not answer:
                    self.bare("[yellow]This question requires an answer.[/yellow]")
                    answer = await self.get_user_input(f"  > ")
            answers[q_id] = answer or default
    
    # Review step
    while True:
        review_text = "\n📝 **Review Your Answers**\n\n"
        for idx, q in enumerate(questions, 1):
            q_id = q["id"]
            answer = answers.get(q_id, "(no answer)")
            if isinstance(answer, list):
                answer = ", ".join(answer)
            review_text += f"  {idx}. {q['question']}\n"
            review_text += f"     → {answer}\n\n"
        
        self.handle_system_message(review_text, markdown=True)
        
        action = await self.get_user_choice(
            "What would you like to do?",
            ["Submit answers", "Edit an answer", "Cancel"]
        )
        
        if action == "Submit answers":
            return answers
        elif action == "Cancel":
            return None
        elif action == "Edit an answer":
            # Let user pick which answer to edit
            edit_options = [
                f"{idx}. {q['question']}" 
                for idx, q in enumerate(questions, 1)
            ]
            edit_choice = await self.get_user_choice(
                "Which answer would you like to edit?",
                edit_options
            )
            
            # Find and re-ask that question
            for idx, q in enumerate(questions, 1):
                if edit_choice.startswith(f"{idx}."):
                    q_id = q["id"]
                    q_type = q.get("type", "text")
                    options = q.get("options", [])
                    
                    if q_type == "choice" and options:
                        answers[q_id] = await self.get_user_choice(
                            q["question"], options
                        )
                    elif q_type == "multi_choice" and options:
                        answers[q_id] = await self._get_multi_choice(
                            q["question"], options
                        )
                    else:
                        answers[q_id] = await self.get_user_input(
                            f"{q['question']}\n  > "
                        )
                    break
```

#### Integration with Existing `user_choice` Tool

The existing `user_choice` tool can be extended to support multi-question mode:

```python
# Updated user_choice tool signature

@tool(group="UserInteraction")
def user_choice(
    context: AgentContext,
    question: str | list[dict],  # Now accepts list for multi-question mode
    options: list[str] = None,   # Only used for single question mode
) -> str | dict:
    """Present one or more questions to the user and get their answers.

    This tool supports two modes:

    1. SINGLE QUESTION MODE (simple): Pass a question string and optional options.
       Returns the user's answer directly as a string.

    2. MULTI-QUESTION MODE (form): Pass a JSON array of question objects.
       Shows questions one at a time, then a summary for review before submission.
       Returns a JSON object mapping question IDs to answers.

    The user can:
    - Select from provided options (if any) using arrow keys
    - Type custom input (always available via "Say something else...")
    - For multi-question: review all answers and edit before submitting
    
    Args:
        question: Either a simple question string, OR a JSON array of question objects.
                  Each question object should have:
                  - id: Unique identifier for the question
                  - question: The question text
                  - type: "text", "choice", or "multi_choice" (default: "text")
                  - options: List of options (required for choice/multi_choice)
                  - required: Whether answer is required (default: True)
        options: For single question mode only - list of option strings.
    
    Returns:
        For single question: The user's answer as a string
        For multi-question: JSON object mapping question IDs to answers
    
    Example (multi-question):
        questions = [
            {"id": "color", "question": "Favorite color?", "type": "choice", "options": ["Red", "Blue", "Green"]},
            {"id": "reason", "question": "Why?", "type": "text"}
        ]
        answers = user_choice(context, json.dumps(questions))
        # Returns: '{"color": "Blue", "reason": "It reminds me of the ocean"}'
    """
```

### 9. UI Integration

#### Keyboard Shortcut

Add a keyboard shortcut to toggle plan mode (similar to thinking mode toggle):

```python
# In hdev.py or user_interface handling
# Ctrl+P to toggle plan mode
```

#### Visual Indicator

Show plan mode status in the prompt:

```python
# Normal: $0.00 >
# Plan mode: 📋 $0.00 [plan-abc123] >
```

#### Plan Mode Welcome Banner

When entering plan mode, display:

```
╔═══════════════════════════════════════════════════════════╗
║                     PLAN MODE ACTIVE                       ║
║                                                            ║
║  📋 Plan ID: abc123                                        ║
║  📝 Title: Implement user authentication                   ║
║                                                            ║
║  Commands:                                                 ║
║    /plan view      - View current plan                     ║
║    /plan approve   - Submit plan for approval              ║
║    /plan exit      - Exit plan mode (save draft)           ║
║                                                            ║
║  The agent will focus on analysis and planning.            ║
║  No code changes will be made until plan is approved.      ║
╚═══════════════════════════════════════════════════════════╝
```

### 10. Integration with Existing Features

#### Compaction Survival

Plans are stored outside the chat history, so they survive compaction. Include plan reference in compacted summaries:

```python
# In compacter.py
if agent_context.active_plan_id:
    summary_prompt += f"\n\nNote: An active plan exists (ID: {agent_context.active_plan_id}). The plan document contains detailed context."
```

#### Session Resume

When resuming a session with an active plan, automatically re-enter plan mode:

```python
# In load_session_data
if session_data.get("active_plan_id"):
    context.enter_plan_mode(session_data["active_plan_id"])
```

#### Memory Integration

Store plan summaries in memory for cross-session reference:

```python
# When a plan is completed
memory_manager.write(
    f"plans/{plan.id}",
    f"# Plan: {plan.title}\n\nCompleted: {plan.completion_notes}\n\n## Key Decisions\n{plan.approach}"
)
```

### 11. Autonomous Engineer Persona Enhancement

Update the autonomous engineer persona to leverage plan mode:

```markdown
## Planning Complex Changes

When facing complex tasks, use plan mode:
1. Enter plan mode with `/plan <topic>` or invoke `enter_plan_mode`
2. Analyze the codebase to understand the current state
3. Ask clarifying questions if requirements are ambiguous
4. Document your implementation approach
5. Get plan approved before making changes
6. Execute the plan systematically, updating progress

Plan mode is particularly valuable for:
- Multi-file refactoring
- New feature implementation
- Architecture changes
- Bug fixes requiring investigation
```

## Implementation Phases

### Phase 1: Core Infrastructure
- [ ] Create `PlanManager` class
- [ ] Define `Plan` data model with proper serialization
- [ ] Implement plan file read/write (markdown format)
- [ ] Add `/plan` CLI command (basic subcommands)

### Phase 2: Multi-Question UI Framework
- [ ] Add `get_clarifications()` method to `UserInterface` ABC
- [ ] Implement terminal UI with Rich/prompt_toolkit
- [ ] Support text, choice, and multi_choice question types
- [ ] Implement review-before-submit flow with edit capability
- [ ] Update `user_choice` tool to support multi-question JSON format

### Phase 3: Agent Tools
- [ ] Implement `enter_plan_mode(topic, reason)` tool
- [ ] Implement `ask_clarifications(plan_id, questions)` tool
- [ ] Implement `update_plan(plan_id, section, content)` tool
- [ ] Implement `add_plan_tasks(plan_id, tasks)` tool
- [ ] Implement `read_plan(plan_id)` tool
- [ ] Implement `exit_plan_mode(plan_id, action)` tool
- [ ] Add plan mode system prompt injection

### Phase 4: State Management
- [ ] Add plan mode state to `AgentContext`
- [ ] Integrate with session save/load
- [ ] Handle plan mode in compaction (reference in summaries)
- [ ] Add plan mode visual indicators in prompt

### Phase 5: UI Polish
- [ ] Add keyboard shortcut (Ctrl+P)
- [ ] Implement plan mode banner
- [ ] Update prompt display with plan indicator
- [ ] Add all `/plan` subcommands (list, view, resume, approve, abandon, execute)

### Phase 6: Integration & Documentation
- [ ] Memory integration for completed plans
- [ ] Update autonomous engineer persona with plan mode guidance
- [ ] Add comprehensive tests for PlanManager and tools
- [ ] Write user documentation and examples
- [ ] Add plan mode to `/tips` output

## Open Questions

1. **Tool Restrictions in Plan Mode**: Should we actually restrict write tools, or rely on prompt guidance? Claude Code uses prompt guidance only.

2. **Plan Approval Flow**: Should plans require explicit user approval before execution, or can the agent proceed after self-review?

3. **Multi-Plan Support**: Should we support multiple concurrent active plans?

4. **Plan Templates**: Should we support custom plan templates per persona?

5. **Plan Sharing**: Should plans be exportable/shareable between sessions or users?

## Alternatives Considered

### Alternative A: Simple Markdown File Approach
Just use a `PLAN.md` file in the project root, similar to how many users work today. 

**Pros**: Simple, no new infrastructure
**Cons**: No structure, no state management, plans lost between sessions

### Alternative B: Memory-Only Plans  
Store plans entirely in the memory system.

**Pros**: Leverages existing infrastructure
**Cons**: Memory is for facts, not structured workflow documents

### Alternative C: Git-Based Plans
Store plans in a git repository for versioning.

**Pros**: Full history, collaboration support
**Cons**: Overly complex for the use case

## Conclusion

The proposed implementation provides a structured yet flexible approach to planning that:
- Enables user-agent collaboration on complex tasks
- Persists plans across sessions and compaction
- Integrates naturally with existing Silica architecture
- Can be initiated by either user or agent
- Produces documentation that serves as both human reference and agent guidance

The phased implementation approach allows for iterative development and user feedback integration.
