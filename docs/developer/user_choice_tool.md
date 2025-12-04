# User Choice Tool

The `user_choice` tool allows the AI assistant to present multiple options to the user and receive their selection. It's rendered as an interactive selector in the terminal, similar to Claude Code's option selector feature.

## Overview

When the AI needs to present discrete options to the user, it can use the `user_choice` tool instead of asking a free-form question. This provides a better user experience by:

1. Showing all available options clearly
2. Allowing keyboard navigation (arrow keys or j/k)
3. Enabling quick selection by number
4. Always providing a "Say something else..." option for custom input

## Tool Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `question` | string | Yes | The question or prompt to display to the user |
| `options` | string | Yes | A JSON array of option strings |

## Usage Example

When the AI wants to present options to the user, it invokes the tool like this:

```json
{
  "name": "user_choice",
  "input": {
    "question": "How would you like me to proceed with this refactoring?",
    "options": "[\"Apply the changes now\", \"Show me a diff first\", \"Create a separate branch\", \"Cancel\"]"
  }
}
```

## Terminal Interaction

When the tool is invoked, the user sees an interactive selector:

```
How would you like me to proceed with this refactoring?

  Use ↑/↓ or j/k to navigate, Enter to select

  ❯ Apply the changes now
    Show me a diff first
    Create a separate branch
    Cancel
    Say something else...
```

### Navigation Keys

| Key | Action |
|-----|--------|
| `↑` or `k` | Move selection up |
| `↓` or `j` | Move selection down |
| `Enter` | Select the highlighted option |
| `1-9` | Quick select by option number |
| `Ctrl+C` | Cancel and return "cancelled" |

### "Say something else..." Option

The final option is always "Say something else..." which, when selected, prompts the user for free-form text input. This ensures users always have an escape hatch if none of the presented options fit their needs.

## Implementation Details

### Tool Registration

The tool is registered in `silica/developer/tools/__init__.py` as part of `ALL_TOOLS`.

### User Interface Method

The `UserInterface` abstract class includes a `get_user_choice()` method:

```python
async def get_user_choice(self, question: str, options: List[str]) -> str:
    """Present multiple options to the user and get their selection."""
```

The `CLIUserInterface` implements this with a full interactive selector using `prompt_toolkit`.

### Fallback Behavior

For user interfaces that don't implement `get_user_choice()`, the tool falls back to a numbered list with text input:

```
Which option?

  1. Option 1
  2. Option 2
  3. Say something else...

Enter your choice (number or text):
```

## Best Practices for AI Usage

The AI should use `user_choice` when:

1. **Discrete options exist**: There are a clear set of possible actions or choices
2. **User confirmation needed**: Before taking significant actions
3. **Branching decisions**: When the next steps depend on user preference
4. **Clarification needed**: When the user's intent could be interpreted multiple ways

The AI should **not** use `user_choice` when:

1. Free-form input is expected (use regular conversation)
2. Yes/No questions (just ask directly)
3. Too many options would be overwhelming (> 7-8 options)

## Return Value

The tool returns the user's selection as a string:

- If an option was selected: The exact text of that option
- If "Say something else..." was selected: The user's custom input
- If cancelled (Ctrl+C): The string "cancelled"

The AI can then use this return value to determine how to proceed.
