"""User choice tool for presenting interactive options to the user.

This tool allows the AI assistant to present multiple options to the user
and receive their selection. It's rendered as an interactive selector in
the terminal with the final option always being "say something else" for
free text input.
"""

from typing import TYPE_CHECKING

from silica.developer.tools.framework import tool

if TYPE_CHECKING:
    from silica.developer.context import AgentContext


@tool(group="UserInterface")
async def user_choice(
    context: "AgentContext",
    question: str,
    options: str,
) -> str:
    """Present multiple options to the user and get their selection.

    Use this tool when you want to give the user a choice between several
    discrete options. The user can select one of the provided options or
    choose to type their own response.

    The options are rendered as an interactive selector in the terminal.
    A "Say something else..." option is automatically added at the end,
    allowing the user to provide free-form text input.

    WHEN TO USE THIS TOOL:
    - Discrete options exist: There are a clear set of possible actions or choices
    - User confirmation needed: Before taking significant actions
    - Branching decisions: When the next steps depend on user preference
    - Clarification needed: When the user's intent could be interpreted multiple ways

    WHEN NOT TO USE THIS TOOL:
    - Free-form input is expected (use regular conversation instead)
    - Simple yes/no questions (just ask directly in your response)
    - Too many options would be overwhelming (keep to 7 or fewer options)

    Args:
        question: The question or prompt to display to the user
        options: A JSON array of option strings (e.g., '["Option 1", "Option 2", "Option 3"]')

    Returns:
        The user's selection (either a selected option or their custom text input)
    """
    import json

    # Parse options from JSON string
    try:
        parsed_options = json.loads(options)
        if not isinstance(parsed_options, list):
            return "Error: options must be a JSON array of strings"
        if not all(isinstance(opt, str) for opt in parsed_options):
            return "Error: all options must be strings"
        if len(parsed_options) == 0:
            return "Error: at least one option must be provided"
    except json.JSONDecodeError as e:
        return f"Error parsing options JSON: {str(e)}"

    # Get the user interface
    user_interface = context.user_interface

    # Check if the user interface supports interactive choice
    if hasattr(user_interface, "get_user_choice"):
        result = await user_interface.get_user_choice(question, parsed_options)
        return result
    else:
        # Fallback for interfaces that don't support interactive choice
        # Present as numbered list and get text input
        options_text = "\n".join(
            f"  {i + 1}. {opt}" for i, opt in enumerate(parsed_options)
        )
        options_text += f"\n  {len(parsed_options) + 1}. Say something else..."

        fallback_prompt = (
            f"{question}\n\n{options_text}\n\nEnter your choice (number or text): "
        )
        user_input = await user_interface.get_user_input(fallback_prompt)

        # Try to parse as number
        try:
            choice_num = int(user_input.strip())
            if 1 <= choice_num <= len(parsed_options):
                return parsed_options[choice_num - 1]
            elif choice_num == len(parsed_options) + 1:
                # "Say something else" was selected
                custom_input = await user_interface.get_user_input(
                    "Enter your response: "
                )
                return custom_input
        except ValueError:
            pass

        # Return as-is if not a valid number
        return user_input
