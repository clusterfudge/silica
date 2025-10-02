from typing import Any

from silica.developer.context import AgentContext
from silica.developer.sandbox import Sandbox
from silica.developer.tools.memory_v2_tools import memory_prompt


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

    base_text = f"You are an AI assistant with access to a sandbox environment. Today's date is {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}.\n\n## Tool Usage Efficiency\n\nWhen multiple tools can be executed independently, you may invoke them in a single response for better performance. Tools automatically manage their own concurrency limits to prevent conflicts and respect API rate limits.\n\nExamples of efficient parallel usage:\n- Checking multiple files: `read_file` for several different files\n- Gathering information: `gmail_search` + `calendar_list_events` + `todo_read`\n- Multiple searches: `web_search` for different topics + `search_memory`\n- Mixed operations: File reads + API calls + memory operations\n- Parallel sub-agents: Multiple `agent` calls for independent research/analysis tasks"

    return {"type": "text", "text": base_text + sandbox_path_info}


def create_system_message(
    agent_context: AgentContext,
    max_estimated_tokens: int = 10_240,
    system_section: dict[str, Any] | None = None,
    include_sandbox: bool = True,
    include_memory: bool = True,
):
    sections: list[dict[str, Any]] = [
        system_section or _create_default_system_section(agent_context)
    ]

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

    if include_sandbox:
        system_message = "The current contents of the sandbox are:\n"
        sandbox_content = render_sandbox_content(agent_context.sandbox, False)
        if estimate_token_count(sandbox_content) > max_estimated_tokens:
            sandbox_content = render_sandbox_content(agent_context.sandbox, True)

        system_message += sandbox_content
        system_message += "\nYou can read, write, and list files/directories, as well as execute some bash commands."
        sections.append({"type": "text", "text": system_message})
    if include_memory:
        system_message = memory_prompt(agent_context)
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
