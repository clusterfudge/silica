from typing import Any

from silica.developer.context import AgentContext
from silica.developer.sandbox import Sandbox


def build_tree(sandbox: Sandbox, limit=1000):
    root = {"is_leaf": False}

    for path in sandbox.get_directory_listing(limit=limit):
        parts = path.split("/")
        current = root

        for i, part in enumerate(parts):
            if i == len(parts) - 1:  # It's a file
                current[part] = {"path": path, "is_leaf": True}
            else:  # It's a directory
                if part not in current:
                    current[part] = {"is_leaf": False}
                current = current[part]

    return root


_STRUCT_KEYS = {"path", "is_leaf"}


def render_tree(tree, indent=""):
    result = ""
    for key, value in sorted(tree.items()):
        if key in _STRUCT_KEYS:
            continue
        if isinstance(value, dict):
            is_leaf = value.get("is_leaf", False)
            if not is_leaf:
                result += f"{indent}{key}/\n"
                result += render_tree(value, indent + "  ")
            else:
                result += f"{indent}{key}\n"
        else:
            result += f"{indent}{key}\n"
    return result


def render_sandbox_content(sandbox, summarize, limit=1000):
    tree = build_tree(sandbox, limit=limit)
    result = "<sandbox_contents>\n"
    result += render_tree(tree)
    result += "</sandbox_contents>\n"
    return result


def _create_default_system_section(agent_context: AgentContext):
    """Create the default system section with sandbox path information."""
    import os

    sandbox_path_info = f"""
## Sandbox Environment Configuration

**Sandbox Root Directory:** `{agent_context.sandbox.root_directory}`
**Current Working Directory:** `{os.getcwd()}`
**Sandbox Mode:** `{agent_context.sandbox.mode.name}`

The sandbox filesystem tools (read_file, write_file, list_directory, edit_file) operate within the sandbox root directory. All paths provided to these tools are relative to the sandbox root.

Shell commands (shell_execute, shell_session_*) operate in the current working directory and may have access to a different filesystem context.

Use the `sandbox_debug` tool to diagnose sandbox configuration issues if file operations behave unexpectedly.
"""

    user_interaction_guidance = """
## User Interaction Guidelines

**Always use tools for user interaction instead of ending your turn with questions:**

- Use `user_choice` for questions with discrete options or when collecting structured information
- Use `ask_clarifications` (in plan mode) to gather multiple related pieces of information
- Avoid ending responses with open-ended questions that require the user to type a new message

**Why this matters:**
- Tool-based questions provide better UX (selectable options, structured input)
- Responses are captured and tracked properly in the conversation
- Enables multi-question flows with review before submission
- Keeps the agent loop flowing without unnecessary back-and-forth

**Examples:**
- Instead of: "Would you like me to proceed with option A or B?"
  Use: `user_choice` with options ["Option A - description", "Option B - description"]
  
- Instead of: "What file should I modify?"
  Use: `user_choice` with discovered file options, or gather context first

- For complex planning: Use `enter_plan_mode` and `ask_clarifications` to collect requirements
"""

    base_text = f"You are an AI assistant with access to a sandbox environment. Today's date is {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}.\n\n## Tool Usage Efficiency\n\nWhen multiple tools can be executed independently, you may invoke them in a single response for better performance. Tools automatically manage their own concurrency limits to prevent conflicts and respect API rate limits.\n\nExamples of efficient parallel usage:\n- Checking multiple files: `read_file` for several different files\n- Gathering information: `gmail_search` + `calendar_list_events` + `todo_read`\n- Multiple searches: `web_search` for different topics + `search_memory`\n- Mixed operations: File reads + API calls + memory operations\n- Parallel sub-agents: Multiple `agent` calls for independent research/analysis tasks"

    return {
        "type": "text",
        "text": base_text + user_interaction_guidance + sandbox_path_info,
    }


def _load_persona_from_disk(agent_context: AgentContext) -> dict[str, Any] | None:
    """Load persona content from disk and wrap it in persona tags.

    This function always reads from disk to ensure the latest persona content
    is used, allowing runtime updates to take effect immediately.

    Priority:
    1. If persona.md exists on disk, use it (takes precedence)
    2. Otherwise, return None to use the system_section fallback

    Args:
        agent_context: The agent context containing persona base directory

    Returns:
        A content block with the persona wrapped in tags, or None if no persona file exists
    """
    from pathlib import Path

    if agent_context.history_base_dir is None or not isinstance(
        agent_context.history_base_dir, Path
    ):
        return None

    persona_file = agent_context.history_base_dir / "persona.md"

    if not persona_file.exists():
        return None

    try:
        with open(persona_file, "r") as f:
            persona_content = f.read().strip()

        if not persona_content:
            return None

        # Resolve @path/to/entry references against memory
        if agent_context.memory_manager:
            persona_content = agent_context.memory_manager.render_content(
                persona_content
            )

        # Get persona name from directory
        persona_name = agent_context.history_base_dir.name

        # Wrap in persona tags for clarity to show the model what it's editing
        wrapped_content = (
            f'<persona name="{persona_name}">\n{persona_content}\n</persona>'
        )

        return {"type": "text", "text": wrapped_content}
    except (IOError, OSError):
        # If we can't read the file, return None
        return None


def _wrap_system_section_with_persona_tags(
    system_section: dict[str, Any], persona_name: str
) -> dict[str, Any]:
    """Wrap a system section content in persona tags.

    This is used for built-in personas that are passed at startup but don't
    have a persona.md file yet.

    Args:
        system_section: The system section to wrap
        persona_name: Name of the persona

    Returns:
        A new system section with content wrapped in persona tags
    """
    if not system_section or "text" not in system_section:
        return system_section

    original_text = system_section["text"]
    wrapped_text = f'<persona name="{persona_name}">\n{original_text}\n</persona>'

    return {**system_section, "text": wrapped_text}


def create_system_message(
    agent_context: AgentContext,
    max_estimated_tokens: int = 10_240,
    system_section: dict[str, Any] | None = None,
    include_sandbox: bool = True,
    include_memory: bool = True,
):
    sections: list[dict[str, Any]] = []

    # Try to load persona from disk first (takes priority over built-ins)
    persona_section = _load_persona_from_disk(agent_context)

    if persona_section:
        # persona.md exists - use it and wrap in tags
        sections.append(persona_section)
    elif system_section:
        # No persona.md but we have a built-in persona - wrap it in tags
        persona_name = (
            agent_context.history_base_dir.name
            if agent_context.history_base_dir
            else "agent"
        )
        wrapped_section = _wrap_system_section_with_persona_tags(
            system_section, persona_name
        )
        sections.append(wrapped_section)
    else:
        # No persona at all - use default system section
        sections.append(_create_default_system_section(agent_context))

    # Add ripgrep guidance regardless of which system section is used
    try:
        from silica.developer.tools.memory import _has_ripgrep

        has_ripgrep = _has_ripgrep()
        if has_ripgrep:
            ripgrep_section = {
                "type": "text",
                "text": '\n## File Search Best Practices\n\n**Use ripgrep (rg) over grep when available for file searching:**\n- `rg "pattern" --type py` instead of `grep -r --include="*.py" "pattern"`\n- Ripgrep is significantly faster and has better defaults\n- Automatically respects .gitignore files and provides colored output\n- Memory system searches automatically use ripgrep when available\n- More efficient for large codebases with better Unicode support',
            }
            sections.append(ripgrep_section)
    except ImportError:
        pass

    # Add loop prevention guidance
    from silica.developer.loop_detection import LOOP_PREVENTION_SYSTEM_PROMPT

    loop_prevention_section = {
        "type": "text",
        "text": LOOP_PREVENTION_SYSTEM_PROMPT,
    }
    sections.append(loop_prevention_section)

    if include_sandbox:
        system_message = "The current contents of the sandbox are:\n"
        sandbox_content = render_sandbox_content(agent_context.sandbox, False)
        if estimate_token_count(sandbox_content) > max_estimated_tokens:
            sandbox_content = render_sandbox_content(agent_context.sandbox, True)

        system_message += sandbox_content
        system_message += "\nYou can read, write, and list files/directories, as well as execute some bash commands."
        sections.append({"type": "text", "text": system_message})
    if include_memory and agent_context.memory_manager.get_tree(depth=1):
        system_message = "\n\nYou have a memory system with which you can interact. Here are the current top-level topics\n\n"
        system_message += "<memory_topics>\n"
        for topic in agent_context.memory_manager.get_tree(depth=1)["items"]:
            system_message += topic + "\n"
        system_message += "</memory_topics>\n"
        sections.append({"type": "text", "text": system_message})

    # add cache_control
    sections[-1]["cache_control"] = {"type": "ephemeral"}

    return sections


def estimate_token_count(text):
    """
    Estimate the number of tokens in a given text.
    This is a rough estimate based on word count and should not be considered exact.
    """
    words = text.split()
    estimated_tokens = int(len(words) * 1.3)
    return estimated_tokens
