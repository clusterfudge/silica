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


_DEFAULT_SYSTEM_SECTION = {
    "type": "text",
    "text": f"You are an AI assistant with access to a sandbox environment. Today's date is {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}.\n\n## Tool Usage Efficiency\n\nWhen multiple tools can be executed independently, you may invoke them in a single response for better performance. Tools automatically manage their own concurrency limits to prevent conflicts and respect API rate limits.\n\nExamples of efficient parallel usage:\n- Checking multiple files: `read_file` for several different files\n- Gathering information: `gmail_search` + `calendar_list_events` + `todo_read`\n- Multiple searches: `web_search` for different topics + `search_memory`\n- Mixed operations: File reads + API calls + memory operations\n- Parallel sub-agents: Multiple `agent` calls for independent research/analysis tasks",
}


def create_system_message(
    agent_context: AgentContext,
    max_estimated_tokens: int = 10_240,
    system_section: dict[str, Any] | None = None,
    include_sandbox: bool = True,
    include_memory: bool = True,
):
    sections: list[dict[str, Any]] = [system_section or _DEFAULT_SYSTEM_SECTION]

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
