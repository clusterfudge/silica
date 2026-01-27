import contextlib
import json
import re
from typing import Any, List

from rich.status import Status

from silica.developer.context import AgentContext
from silica.developer.models import MODEL_MAP
from .framework import tool
from silica.developer.user_interface import UserInterface
from ..utils import wrap_text_as_content_block

# Type hint imports
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from silica.developer.mcp import MCPToolManager, MCPConfig


@tool(group="Agent")
async def agent(
    context: "AgentContext",
    prompt: str,
    tool_names: str = None,
    model: str = None,
    mcp_servers: str = None,
    tool_use_id: str = None,
):
    """Run a prompt through a sub-agent with a limited set of tools.
    Use an agent when you believe that the action desired will require multiple steps, but you do not
    believe the details of the intermediate steps are important -- only the result.
    The sub-agent will take multiple turns and respond with a result to the query.
    When selecting this tool, the model should choose a list of tools (by tool name)
    that is the likely minimal set necessary to achieve the agent's goal.
    Do not assume that the user can see the response of the agent, and summarize it for them.
    Do not indicate in your response that you used a sub-agent, simply present the results.

    EFFICIENCY NOTE: Multiple sub-agents can run concurrently! When you have independent tasks
    that can be parallelized, feel free to invoke multiple agent tools simultaneously.
    Examples: researching different topics, analyzing separate files, or performing
    unrelated operations. Each sub-agent operates independently and safely.

    Args:
        prompt: the initial prompt question to ask the
        tool_names: optional, a comma separated list of tool names from the existing tools to provide to the sub-agent. If not specified, the agent will have access to all tools.
        model: optional model alias to use for the sub-agent. Supported aliases:
            - "light": Use Claude 3.5 Haiku - faster and more cost-effective for simple tasks like
                       information retrieval, basic formatting, or straightforward reasoning
            - "smart": Use Claude 4 Sonnet - better for complex tasks requiring deeper reasoning,
                       detailed analysis, and more sophisticated responses
            - "advances": Use Claude 4 Opus - most advanced tasks requiring deeper reasoning, use sparingly.

              If not provided or invalid, uses the parent context's model.
        mcp_servers: optional MCP servers for the sub-agent. Can be:
            - Comma-separated server names referencing configured servers (e.g., "sqlite,github")
            - JSON object with inline server definitions (e.g., '{"sqlite": {"command": "uvx", "args": ["mcp-server-sqlite"]}}')
            The sub-agent gets its own isolated MCP connections (not shared with parent).
        tool_use_id: Internal parameter provided by the framework, used as the session ID for the sub-agent.
    """

    tool_names_list = (
        [tool_name.strip(",").strip() for tool_name in re.split(r"[ ,]", tool_names)]
        if tool_names
        else []
    )

    # Parse mcp_servers parameter
    mcp_config = _parse_mcp_servers(mcp_servers)

    return await run_agent(
        context,
        prompt,
        tool_names_list,
        system=None,
        model=model,
        mcp_servers=mcp_config,
        tool_use_id=tool_use_id,
    )


def _parse_mcp_servers(mcp_servers: str | None) -> dict | list[str] | None:
    """Parse the mcp_servers parameter.

    Args:
        mcp_servers: Either comma-separated server names or JSON config

    Returns:
        - None if no servers specified
        - List of server names for named references
        - Dict of server configs for inline definitions
    """
    if not mcp_servers:
        return None

    mcp_servers = mcp_servers.strip()
    if not mcp_servers:
        return None

    # Try parsing as JSON first
    if mcp_servers.startswith("{"):
        try:
            return json.loads(mcp_servers)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid MCP server JSON: {e}")

    # Otherwise, treat as comma-separated server names
    names = [name.strip() for name in mcp_servers.split(",") if name.strip()]
    return names if names else None


async def run_agent(
    context: "AgentContext",
    prompt: str,
    tool_names: List[str],
    system: str | None = None,
    model: str = None,
    mcp_servers: dict | list[str] | None = None,
    tool_use_id: str = None,
):
    from silica.developer.agent_loop import run

    tool_name_str = ",".join(tool_names)
    if len(tool_name_str) > 64:
        tool_name_str = ",".join(name[:3] for name in tool_names)

    with context.user_interface.status(
        f"Initiating sub-agent\\[{tool_name_str}]: {prompt}"
    ) as status:
        ui = CaptureInterface(parent=context.user_interface, status=status)

        # Create a sub-agent context with the current context as parent
        # Use the tool_use_id as the session_id if provided
        sub_agent_context = context.with_user_interface(ui, session_id=tool_use_id)

        # Handle the model parameter if provided
        if model:
            # Define model aliases to model keys in MODEL_MAP
            model_aliases = {
                "light": "haiku",  # Faster, more cost-effective model
                "smart": "sonnet",  # More capable for complex reasoning
                "advanced": "opus",  # most advanced, most expensive
            }

            # Check if the provided model alias is valid
            if model in model_aliases:
                # Get the model key from aliases
                model_key = model_aliases[model]

                # Get the model spec from MODEL_MAP
                if model_key in MODEL_MAP:
                    # Update the sub_agent_context with the model spec from MODEL_MAP
                    sub_agent_context.model_spec = MODEL_MAP[model_key]

        # Set up MCP manager for subagent if configured
        mcp_manager = await _setup_subagent_mcp(mcp_servers, context, ui)

        try:
            system_block = wrap_text_as_content_block(system) if system else None
            # Run the agent with single response mode
            chat_history = await run(
                agent_context=sub_agent_context,
                initial_prompt=prompt,
                system_prompt=system_block,
                single_response=True,
                tool_names=tool_names,
                mcp_manager=mcp_manager,
            )

            # Make sure the chat history is flushed in case run() didn't do it
            # (this can happen if there's an exception in run())
            sub_agent_context.flush(chat_history)

            # Get the final assistant message from chat history
            for message in reversed(chat_history):
                if message["role"] == "assistant":
                    # Handle both string and list content formats
                    if isinstance(message["content"], str):
                        return message["content"]
                    elif isinstance(message["content"], list):
                        # Concatenate all text blocks and ensure proper markdown formatting
                        # This ensures that code blocks and other formatting is preserved
                        return "".join(
                            block.text
                            for block in message["content"]
                            if hasattr(block, "text")
                        )

            return "No response generated"
        except Exception:
            # If there's an exception, still try to flush any partial chat history
            if "chat_history" in locals() and chat_history:
                sub_agent_context.flush(chat_history)
            # Re-raise the exception
            raise
        finally:
            # Clean up MCP connections if we created them
            if mcp_manager is not None:
                await mcp_manager.disconnect_all()


async def _setup_subagent_mcp(
    mcp_servers: dict | list[str] | None,
    context: "AgentContext",
    ui: "UserInterface",
) -> "MCPToolManager | None":
    """Set up MCP manager for a subagent.

    Args:
        mcp_servers: Either server names or inline config
        context: Parent agent context (for loading named servers)
        ui: User interface for status messages

    Returns:
        MCPToolManager or None if no servers configured
    """
    if not mcp_servers:
        return None

    try:
        from silica.developer.mcp import MCPToolManager

        manager = MCPToolManager()

        if isinstance(mcp_servers, list):
            # Named server references - load from parent's config
            config = _load_named_servers(mcp_servers, context)
            if config:
                await manager.connect_servers(config)
        elif isinstance(mcp_servers, dict):
            # Inline server definitions
            config = _parse_inline_config(mcp_servers)
            if config:
                await manager.connect_servers(config)

        return manager if manager._clients else None

    except ImportError:
        # MCP not available
        return None
    except Exception as e:
        # Log error but don't fail the subagent
        import logging

        logging.getLogger(__name__).warning(f"Failed to set up MCP for subagent: {e}")
        return None


def _load_named_servers(
    server_names: list[str], context: "AgentContext"
) -> "MCPConfig | None":
    """Load named MCP servers from the parent's config."""
    from pathlib import Path

    try:
        from silica.developer.mcp import load_mcp_config

        # Determine persona name from history_base_dir
        persona_name = None
        if context.history_base_dir:
            # Extract persona name from path like ~/.silica/personas/{persona_name}
            history_path = Path(context.history_base_dir)
            if history_path.parent.name == "personas":
                persona_name = history_path.name

        # Get project root from working directory
        project_root = Path.cwd()

        # Load merged config (function handles path construction internally)
        full_config = load_mcp_config(
            project_root=project_root,
            persona=persona_name,
        )

        if not full_config:
            return None

        # Filter to only the requested servers
        from silica.developer.mcp import MCPConfig

        filtered_servers = {
            name: cfg
            for name, cfg in full_config.servers.items()
            if name in server_names
        }

        if not filtered_servers:
            return None

        return MCPConfig(servers=filtered_servers)

    except Exception:
        return None


def _parse_inline_config(config_dict: dict) -> "MCPConfig | None":
    """Parse inline MCP server configuration."""
    try:
        from silica.developer.mcp import MCPConfig, MCPServerConfig

        servers = {}
        for name, cfg in config_dict.items():
            servers[name] = MCPServerConfig.from_dict(name, cfg)

        return MCPConfig(servers=servers) if servers else None

    except Exception:
        return None


class CaptureInterface(UserInterface):
    async def get_user_input(self, prompt: str = "") -> str:
        pass

    def display_welcome_message(self) -> None:
        pass

    def status(
        self, message: str, spinner: str = None, update=False
    ) -> contextlib.AbstractContextManager:
        if update:
            self._status.update(message, spinner=spinner or "aesthetic")
        return self._status

    def __init__(self, parent: UserInterface, status: Status) -> None:
        self.output = []
        self.parent = parent
        self._status = status
        self._prior_renderable = status.renderable

    def handle_system_message(self, message, markdown=True, live=None):
        self.output.append(message)

    def handle_user_input(self, message):
        self.output.append(message)

    def handle_assistant_message(self, message):
        self.output.append(message)

    def handle_tool_use(self, tool_name, tool_input, tool_use_id=None):
        message = f"Using tool {tool_name} with input {tool_input}"
        self.bare(self._prior_renderable)
        self.bare("")
        self._prior_renderable = message
        self.status(message, update=True)
        self.output.append(message)

    def handle_tool_result(self, tool_name, result, live=None, tool_use_id=None):
        self.output.append(f"Tool {tool_name} result: {result}")

    def display_token_count(
        self,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        total_cost,
        cached_tokens=None,
        conversation_size=None,
        context_window=None,
        thinking_tokens: int | None = None,
        thinking_cost: float | None = None,
        elapsed_seconds: float | None = None,
        plan_slug: str | None = None,
        plan_tasks_completed: int | None = None,
        plan_tasks_verified: int | None = None,
        plan_tasks_total: int | None = None,
    ):
        pass

    def permission_callback(self, operation, path, sandbox_mode, action_arguments):
        return True

    def permission_rendering_callback(self, operation, path, action_arguments):
        return True

    def bare(self, message: str | Any, live=None) -> None:
        return self.parent.bare(message, live=live)
