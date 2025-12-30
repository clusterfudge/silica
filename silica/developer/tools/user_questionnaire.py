"""User questionnaire tool for collecting multiple pieces of input interactively.

This tool allows the AI assistant to present a series of questions to the user,
where each question can either be free-form text or a selection from options.
The user answers each question interactively, then reviews a summary before
confirming submission.
"""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from silica.developer.tools.framework import tool

if TYPE_CHECKING:
    from silica.developer.context import AgentContext


@dataclass
class Question:
    """A single question in the questionnaire."""

    id: str
    prompt: str
    options: list[str] | None = None  # None means free-form text input
    default: str | None = None


@tool(group="UserInterface")
async def user_questionnaire(
    context: "AgentContext",
    title: str,
    questions: str,
) -> str:
    """Present a multi-question form to the user and collect their answers.

    Use this tool when you need to gather multiple pieces of information from
    the user at once. Each question is presented one at a time, allowing the
    user to either select from options or provide free-form text. After all
    questions are answered, a summary is shown for review before submission.

    The user can:
    - Navigate through questions one at a time
    - Select from provided options (if any) or type custom input
    - Review all answers in a summary before confirming
    - Go back and edit any answer before final submission

    WHEN TO USE THIS TOOL:
    - Need multiple pieces of related information (e.g., form fields)
    - Want to guide user through a structured workflow
    - Collecting configuration or preferences
    - Gathering details for a complex task

    WHEN NOT TO USE THIS TOOL:
    - Single question (use user_choice or regular conversation)
    - Questions that depend heavily on previous answers (ask sequentially)
    - Very long questionnaires (break into smaller logical groups)

    Args:
        title: Title/header for the questionnaire (e.g., "New Project Setup")
        questions: JSON array of question objects with fields: id (string), prompt (string), options (optional array), default (optional string). Example: [{"id": "name", "prompt": "Project name?"}, {"id": "type", "prompt": "Type?", "options": ["web", "cli"]}]

    Returns:
        JSON object mapping question IDs to user's answers, or {"cancelled": true} if user cancels
    """
    # Parse questions from JSON
    try:
        parsed_questions = json.loads(questions)
        if not isinstance(parsed_questions, list):
            return json.dumps({"error": "questions must be a JSON array"})
        if len(parsed_questions) == 0:
            return json.dumps({"error": "at least one question must be provided"})
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {str(e)}"})

    # Validate and convert to Question objects
    question_list: list[Question] = []
    for i, q in enumerate(parsed_questions):
        if not isinstance(q, dict):
            return json.dumps({"error": f"Question {i} must be an object"})
        if "id" not in q or "prompt" not in q:
            return json.dumps({"error": f"Question {i} must have 'id' and 'prompt'"})

        question_list.append(
            Question(
                id=q["id"],
                prompt=q["prompt"],
                options=q.get("options"),
                default=q.get("default"),
            )
        )

    # Get the user interface
    user_interface = context.user_interface

    # Check if the user interface supports the questionnaire flow
    if hasattr(user_interface, "run_questionnaire"):
        answers = await user_interface.run_questionnaire(title, question_list)
        if answers is None:
            return json.dumps({"cancelled": True})
        return json.dumps(answers)

    # Fallback implementation for interfaces without native support
    answers = await _fallback_questionnaire(user_interface, title, question_list)
    if answers is None:
        return json.dumps({"cancelled": True})
    return json.dumps(answers)


async def _fallback_questionnaire(
    user_interface, title: str, questions: list[Question]
) -> dict | None:
    """Fallback implementation using basic input methods."""
    from rich.console import Console
    from rich.table import Table

    console = Console()

    console.print(f"\n[bold cyan]━━━ {title} ━━━[/bold cyan]\n")
    console.print(
        f"[dim]Answer {len(questions)} questions. You can review before submitting.[/dim]\n"
    )

    answers: dict[str, str] = {}

    # Collect answers for each question
    for i, q in enumerate(questions):
        console.print(f"[bold]Question {i + 1}/{len(questions)}:[/bold] {q.prompt}")

        if q.default:
            console.print(f"[dim]Default: {q.default}[/dim]")

        if q.options:
            # Present options
            if hasattr(user_interface, "get_user_choice"):
                answer = await user_interface.get_user_choice(
                    f"({i + 1}/{len(questions)}) {q.prompt}",
                    q.options,
                )
            else:
                # Text-based fallback
                options_text = ", ".join(
                    f"{j + 1}={opt}" for j, opt in enumerate(q.options)
                )
                prompt = f"Choose [{options_text}]: "
                answer = await user_interface.get_user_input(prompt)
                # Try to map number to option
                try:
                    idx = int(answer.strip()) - 1
                    if 0 <= idx < len(q.options):
                        answer = q.options[idx]
                except ValueError:
                    pass
        else:
            # Free-form text input
            default_hint = f" [{q.default}]" if q.default else ""
            prompt = f"Your answer{default_hint}: "
            answer = await user_interface.get_user_input(prompt)

            # Use default if empty
            if not answer.strip() and q.default:
                answer = q.default

        answers[q.id] = answer.strip() if answer else (q.default or "")
        console.print()

    # Show summary
    while True:
        console.print("\n[bold cyan]━━━ Review Your Answers ━━━[/bold cyan]\n")

        table = Table(show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=3)
        table.add_column("Question", style="cyan")
        table.add_column("Answer", style="green")

        for i, q in enumerate(questions):
            table.add_row(
                str(i + 1),
                q.prompt[:40] + "..." if len(q.prompt) > 40 else q.prompt,
                answers[q.id],
            )

        console.print(table)
        console.print()

        # Ask for confirmation
        if hasattr(user_interface, "get_user_choice"):
            action = await user_interface.get_user_choice(
                "What would you like to do?",
                ["Submit answers", "Edit an answer", "Cancel"],
            )
        else:
            action = await user_interface.get_user_input(
                "[S]ubmit, [E]dit, or [C]ancel? "
            )
            action = action.strip().lower()
            if action in ("s", "submit"):
                action = "Submit answers"
            elif action in ("e", "edit"):
                action = "Edit an answer"
            elif action in ("c", "cancel"):
                action = "Cancel"

        if action == "Submit answers":
            console.print("[green]✓ Answers submitted[/green]\n")
            return answers
        elif action == "Cancel":
            console.print("[yellow]Cancelled[/yellow]\n")
            return None
        elif action == "Edit an answer":
            # Ask which question to edit
            edit_options = [
                f"{i + 1}. {q.prompt[:50]}" for i, q in enumerate(questions)
            ]
            if hasattr(user_interface, "get_user_choice"):
                edit_choice = await user_interface.get_user_choice(
                    "Which question do you want to edit?",
                    edit_options,
                )
                try:
                    edit_idx = int(edit_choice.split(".")[0]) - 1
                except (ValueError, IndexError):
                    # Try to find by matching
                    edit_idx = next(
                        (i for i, opt in enumerate(edit_options) if opt == edit_choice),
                        0,
                    )
            else:
                edit_input = await user_interface.get_user_input(
                    f"Enter question number (1-{len(questions)}): "
                )
                try:
                    edit_idx = int(edit_input.strip()) - 1
                except ValueError:
                    edit_idx = 0

            if 0 <= edit_idx < len(questions):
                q = questions[edit_idx]
                console.print(f"\n[bold]Editing:[/bold] {q.prompt}")
                console.print(f"[dim]Current answer: {answers[q.id]}[/dim]\n")

                if q.options:
                    if hasattr(user_interface, "get_user_choice"):
                        new_answer = await user_interface.get_user_choice(
                            f"New answer for: {q.prompt}",
                            q.options,
                        )
                    else:
                        new_answer = await user_interface.get_user_input("New answer: ")
                else:
                    new_answer = await user_interface.get_user_input("New answer: ")

                if new_answer.strip():
                    answers[q.id] = new_answer.strip()
                    console.print("[green]✓ Answer updated[/green]")
