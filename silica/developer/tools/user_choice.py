"""User choice tool for presenting interactive questions to the user.

This tool allows the AI assistant to present one or more questions to the user,
where each question can either be free-form text or a selection from options.
For multiple questions, the user answers each interactively, then reviews a
summary before confirming submission.
"""

import json
from typing import TYPE_CHECKING

from silica.developer.tools.framework import tool

if TYPE_CHECKING:
    from silica.developer.context import AgentContext


@tool(group="UserInterface")
async def user_choice(
    context: "AgentContext",
    question: str,
    options: str = "",
) -> str:
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

    WHEN TO USE THIS TOOL:
    - Discrete options exist: There are a clear set of possible actions or choices
    - User confirmation needed: Before taking significant actions
    - Branching decisions: When the next steps depend on user preference
    - Collecting multiple related pieces of information (use multi-question mode)

    WHEN NOT TO USE THIS TOOL:
    - Free-form input expected with no guidance (use regular conversation)
    - Simple yes/no (just ask directly in your response)

    Args:
        question: Either a simple question string, OR a JSON array of question objects.
            For multi-question mode, each object has: id (string), prompt (string),
            options (optional array), default (optional string).
        options: For single question mode only - JSON array of option strings.
            Ignored if question is a JSON array (multi-question mode).

    Returns:
        Single question: The selected option or custom text input.
        Multi-question: JSON object mapping question IDs to answers, or {"cancelled": true}.

    Examples:
        # Single question with options
        user_choice(question="Continue?", options='["Yes", "No", "Ask me later"]')

        # Single question, free-form
        user_choice(question="What should I name this file?")

        # Multiple questions (form mode)
        user_choice(question='[
            {"id": "name", "prompt": "Project name?"},
            {"id": "type", "prompt": "Type?", "options": ["web", "cli", "library"]}
        ]')
    """
    # Detect mode: multi-question if question parses as a JSON array
    is_multi_question = False
    questions_list = None

    if question.strip().startswith("["):
        try:
            parsed = json.loads(question)
            if isinstance(parsed, list) and len(parsed) > 0:
                # Validate it looks like question objects
                # Support both "prompt" and "question" field names
                if all(
                    isinstance(q, dict)
                    and "id" in q
                    and ("prompt" in q or "question" in q)
                    for q in parsed
                ):
                    is_multi_question = True
                    # Normalize to use "prompt" internally
                    questions_list = []
                    for q in parsed:
                        normalized = dict(q)
                        if "question" in normalized and "prompt" not in normalized:
                            normalized["prompt"] = normalized.pop("question")
                        questions_list.append(normalized)
        except json.JSONDecodeError:
            pass  # Not valid JSON, treat as single question

    if is_multi_question:
        return await _handle_multi_question(context, questions_list)
    else:
        return await _handle_single_question(context, question, options)


async def _handle_single_question(
    context: "AgentContext",
    question: str,
    options: str,
) -> str:
    """Handle single question mode (original user_choice behavior)."""
    user_interface = context.user_interface

    # Parse options if provided
    parsed_options = None
    if options and options.strip():
        try:
            parsed_options = json.loads(options)
            if not isinstance(parsed_options, list):
                return "Error: options must be a JSON array of strings"
            if not all(isinstance(opt, str) for opt in parsed_options):
                return "Error: all options must be strings"
            if len(parsed_options) == 0:
                parsed_options = None
        except json.JSONDecodeError as e:
            return f"Error parsing options JSON: {str(e)}"

    if parsed_options:
        # Use interactive choice if available
        if hasattr(user_interface, "get_user_choice"):
            result = await user_interface.get_user_choice(question, parsed_options)
            return result
        else:
            # Fallback: numbered list
            options_text = "\n".join(
                f"  {i + 1}. {opt}" for i, opt in enumerate(parsed_options)
            )
            options_text += f"\n  {len(parsed_options) + 1}. Say something else..."

            fallback_prompt = (
                f"{question}\n\n{options_text}\n\nEnter your choice (number or text): "
            )
            user_input = await user_interface.get_user_input(fallback_prompt)

            try:
                choice_num = int(user_input.strip())
                if 1 <= choice_num <= len(parsed_options):
                    return parsed_options[choice_num - 1]
                elif choice_num == len(parsed_options) + 1:
                    custom_input = await user_interface.get_user_input(
                        "Enter your response: "
                    )
                    return custom_input
            except ValueError:
                pass

            return user_input
    else:
        # Free-form text input
        result = await user_interface.get_user_input(f"{question}\n→ ")
        return result


async def _handle_multi_question(
    context: "AgentContext",
    questions: list[dict],
) -> str:
    """Handle multi-question mode (form/questionnaire behavior)."""
    user_interface = context.user_interface

    # Check if the user interface supports the questionnaire flow
    if hasattr(user_interface, "run_questionnaire"):
        # Convert dicts to Question-like objects
        from dataclasses import dataclass

        @dataclass
        class Question:
            id: str
            prompt: str
            options: list[str] | None = None
            default: str | None = None

        question_objs = [
            Question(
                id=q["id"],
                prompt=q["prompt"],
                options=q.get("options"),
                default=q.get("default"),
            )
            for q in questions
        ]

        # Derive title from first question or use generic
        title = "Questions"
        if len(questions) == 1:
            title = questions[0]["prompt"][:50]

        answers = await user_interface.run_questionnaire(title, question_objs)
        if answers is None:
            return json.dumps({"cancelled": True})
        return json.dumps(answers)

    # Fallback implementation
    return await _fallback_multi_question(user_interface, questions)


async def _fallback_multi_question(
    user_interface,
    questions: list[dict],
) -> str:
    """Fallback implementation for multi-question mode."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    answers: dict[str, str] = {}

    console.print(f"\n[bold cyan]━━━ Questions ({len(questions)}) ━━━[/bold cyan]\n")

    # Collect answers
    for i, q in enumerate(questions):
        console.print(f"[bold]({i + 1}/{len(questions)}) {q['prompt']}[/bold]")

        if q.get("default"):
            console.print(f"[dim]Default: {q['default']}[/dim]")

        if q.get("options"):
            if hasattr(user_interface, "get_user_choice"):
                answer = await user_interface.get_user_choice(
                    f"({i + 1}/{len(questions)}) {q['prompt']}",
                    q["options"],
                )
            else:
                options_text = ", ".join(
                    f"{j + 1}={opt}" for j, opt in enumerate(q["options"])
                )
                answer = await user_interface.get_user_input(f"[{options_text}]: ")
                try:
                    idx = int(answer.strip()) - 1
                    if 0 <= idx < len(q["options"]):
                        answer = q["options"][idx]
                except ValueError:
                    pass
        else:
            answer = await user_interface.get_user_input("→ ")
            if not answer.strip() and q.get("default"):
                answer = q["default"]

        answers[q["id"]] = answer.strip() if answer else (q.get("default") or "")
        console.print()

    # Review loop
    while True:
        console.print("\n[bold cyan]━━━ Review ━━━[/bold cyan]\n")

        table = Table(show_header=True, header_style="bold")
        table.add_column("#", width=3)
        table.add_column("Question")
        table.add_column("Answer", style="green")

        for i, q in enumerate(questions):
            prompt = q["prompt"][:40] + "..." if len(q["prompt"]) > 40 else q["prompt"]
            table.add_row(str(i + 1), prompt, answers[q["id"]])

        console.print(table)

        if hasattr(user_interface, "get_user_choice"):
            action = await user_interface.get_user_choice(
                "What would you like to do?",
                ["Submit", "Edit an answer", "Cancel"],
            )
        else:
            action = await user_interface.get_user_input("[S]ubmit/[E]dit/[C]ancel: ")
            action = action.strip().lower()
            if action in ("s", "submit"):
                action = "Submit"
            elif action in ("e", "edit"):
                action = "Edit an answer"
            else:
                action = "Cancel"

        if action == "Submit":
            return json.dumps(answers)
        elif action == "Cancel" or action == "cancelled":
            return json.dumps({"cancelled": True})
        elif action == "Edit an answer":
            edit_prompt = f"Which question? (1-{len(questions)}): "
            edit_input = await user_interface.get_user_input(edit_prompt)
            try:
                idx = int(edit_input.strip()) - 1
                if 0 <= idx < len(questions):
                    q = questions[idx]
                    console.print(f"\n[bold]Editing:[/bold] {q['prompt']}")
                    if q.get("options"):
                        new_answer = (
                            await user_interface.get_user_choice(
                                "New answer:", q["options"]
                            )
                            if hasattr(user_interface, "get_user_choice")
                            else await user_interface.get_user_input("New answer: ")
                        )
                    else:
                        new_answer = await user_interface.get_user_input("New answer: ")
                    if new_answer and new_answer != "cancelled":
                        answers[q["id"]] = new_answer.strip()
            except ValueError:
                pass
